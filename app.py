from hashlib import sha256
import streamlit as st
import pandas as pd
import plotly.express as px
import importlib
import simulator

# A running Cloud worker can retain the previous helper module after a code update.
# Refresh it when the new UI needs a function absent from that loaded copy.
if not all(hasattr(simulator, name) for name in (
    'sample_data', 'template', 'read_inputs', 'parse_choices',
    'custom_template', 'curriculum_allocation', 'estimate_week', 'elective_input_version', 'expand_common_requirements', 'common_targets_for',
)):
    simulator = importlib.reload(simulator)

from simulator import (sample_data, template, read_inputs, parse_choices, custom_template, curriculum_allocation, estimate_week, common_targets_for)

st.set_page_config(page_title='School Period Length Impact Simulator', layout='wide')
st.title('School Period Length Impact Simulator')
st.caption('Version 1 · Decision support for Singapore secondary school planners')
st.info('Synthetic examples only — these are not official MOE minimums. This view calculates weekly subject periods and curriculum hours. The weekly layout below is illustrative and does not validate a subject timetable.')
with st.expander('1. Set up your Excel template', expanded=True):
    st.write('Enter your choices below, one per line. Click outside a box after editing to update the download.')
    columns = st.columns(3)
    with columns[0]:
        level_choices = st.text_area('Levels', 'Sec 1\nSec 2\nSec 3\nSec 4', key='template_levels')
    with columns[1]:
        stream_choices = st.text_area('Streams', 'G3\nG2\nG1\nCMN', key='template_streams')
    with columns[2]:
        subject_choices = st.text_area('Subjects', 'English\nMathematics\nMother Tongue\nScience', key='template_subjects')
    elective_group_choices = st.text_area('Elective groups (optional, one name per line)', '', key='template_elective_groups', help='For example Humanities choice or Arts choice. Assign subjects to these groups in Excel; leave compulsory subjects ungrouped.')
    unit_choices = st.multiselect('Units available in the template', ['minutes', 'periods'], default=['minutes', 'periods'], key='template_units')
    st.caption('CMN means common to the actual streams you list above. The workbook saves those recipients on Stream Settings; change them there when using different stream names. Enter common subjects once under CMN; use stream-specific rows for differences. Delete unused template rows. A specific row for the same subject replaces its CMN row, including its elective group.')
    st.caption('Only minutes and periods are supported. The first selected unit is prefilled; change it per row in Excel.')
    try:
        template_bytes = custom_template(parse_choices(level_choices), parse_choices(stream_choices), parse_choices(subject_choices), unit_choices, parse_choices(elective_group_choices))
    except ValueError as error:
        st.warning(str(error))
        st.download_button('Download my Excel template', b'', 'school_period_input_template.xlsx', disabled=True)
    else:
        st.download_button('Download my Excel template', template_bytes, 'school_period_input_template.xlsx', type='primary')
    st.caption('The workbook has a row for every level × stream × subject combination. Fill in the numeric requirements and delete rows that do not apply. Check the illustrative school-day times and breaks before uploading. These choices prepare the download; they do not change the dashboard below.')
    st.download_button('Download synthetic example instead', template(), 'school_period_example.xlsx')
st.subheader('2. Upload your completed workbook')
st.caption('In Excel, maintain dropdown choices on the Lists sheet. Keep Unit as minutes or periods. Numeric requirements are entered on Subject Requirements.')
upload = st.file_uploader('Upload completed template', type=['xlsx'])
if upload:
    try:
        inputs = read_inputs(upload)
    except Exception as e:
        st.error(f'Cannot read workbook: {e}')
        st.stop()
else:
    inputs = sample_data()
with st.expander('Edit inputs', expanded=False):
    st.caption('Enter a Stream for every subject row (for example G1, G2 or G3). Enter a separate full set of subjects for each stream. School day settings and fixed activities determine the weekly layout. Earliest dismissal is mandatory; any gap to that time is shown as unallocated school time. These settings do not change curriculum hours. Use HH:MM times. Each level needs Monday–Friday. Fixed activities are mandatory, must lie within the day, and cannot overlap. Add as many activity rows as needed in the third sheet.')
    edited = []
    for name, frame in zip(['Subject Requirements', 'School Day Settings', 'Fixed Activities'], inputs):
        st.subheader(name)
        edited.append(st.data_editor(frame, num_rows='dynamic', key=f'input_{name}_{upload.file_id if upload else "sample"}', width='stretch'))
s, d, a = edited
st.caption('CMN rows are included in the configured recipients’ totals and weekly layouts; CMN is not a separate student stream. A stream-specific row replaces the common row for the same subject. In Subject Requirements, leave Elective group blank for compulsory subjects. Give alternative subjects the same group name. Each student chooses one subject from every group in their level and stream.')
with st.expander('Common stream settings', expanded=s.Stream.str.upper().eq('CMN').any()):
    common_text = st.text_area('Streams receiving CMN (one per line)', '\n'.join(common_targets_for(inputs[0])), key=f'common_targets_{upload.file_id if upload else "sample"}')
    common_streams = parse_choices(common_text)
    st.caption('List every actual stream that should receive CMN. Do not include CMN itself. These recipients apply at each level containing common requirements; explicit stream-specific rows still override the same common subject.')
    st.write('CMN recipients: ' + (', '.join(common_streams) if common_streams else 'none — required if using CMN'))
st.subheader('3. Subject periods and weekly curriculum time')
length = st.select_slider('Minutes per period', options=[15, 20, 30, 35], value=30, key='period_length')
st.caption('Minimum periods = required weekly minutes ÷ minutes per period, rounded up separately for each subject. Period-based requirements use the reference duration in your input.')
try:
    base, _ = curriculum_allocation(s, length, common_streams=common_streams)
except (ValueError, TypeError, KeyError) as error:
    st.error(f'Please correct subject requirements: {error}')
    st.stop()

elective_choices = {}
options_by_group = base[base['Elective group'] != '']
if not options_by_group.empty:
    st.write('Choose one elective from each group for this example pathway')
    st.caption('These choices determine the curriculum totals and weekly layout below. The first option is selected initially. CMN elective options are inherited by each stream; choices remain independent per stream. Groups are independent; this does not check subject-combination restrictions.')
    for (level, stream, group), options in options_by_group.groupby(['Level', 'Stream', 'Elective group'], sort=False):
        key = 'elective_' + sha256(repr((level, stream, group, list(options.Subject))).encode()).hexdigest()[:20]
        elective_choices[(level, stream, group)] = st.selectbox(f'{level} / {stream} — {group}', list(options.Subject), key=key)

if 'period_adjustments' not in st.session_state:
    st.session_state.period_adjustments = {}
if 'adjustment_reset' not in st.session_state:
    st.session_state.adjustment_reset = 0
if st.button('Reset all period adjustments'):
    st.session_state.period_adjustments = {}
    st.session_state.adjustment_reset += 1
identities = list(base[['Level', 'Stream', 'Subject']].itertuples(index=False, name=None))
# Key by subject identity and duration, so edits cannot migrate to a different row/scenario.
adjustments = {identity: st.session_state.period_adjustments.get((length, *identity), 0) for identity in identities}
allocation_error = None
try:
    displayed, totals = curriculum_allocation(s, length, adjustments, elective_choices, common_streams=common_streams)
except ValueError as error:
    allocation_error = str(error)
    displayed = base.copy()
    displayed['Adjustment (periods)'] = [adjustments[identity] for identity in identities]
    for column in ['Allocated periods', 'Actual minutes', 'Balance minutes', 'Requirement status']:
        displayed[column] = None

input_signature = sha256(base[['Level', 'Stream', 'Subject', 'Required minutes', 'Minimum periods']].to_json(orient='split').encode()).hexdigest()[:16]
editor_key = f'period_allocation_{length}_{input_signature}_{st.session_state.adjustment_reset}'
def save_adjustments():
    changes = st.session_state[editor_key].get('edited_rows', {})
    for index, values in changes.items():
        if 'Adjustment (periods)' in values:
            st.session_state.period_adjustments[(length, *identities[int(index)])] = values['Adjustment (periods)']

st.write('Adjust periods for each subject')
st.caption('Enter 1 or 2 to add periods; enter -1 or -2 to subtract. Only the Adjustment column is editable. Changes update the allocated periods, minutes and totals. Adjustments are saved separately for each period length during this session.')
st.data_editor(displayed, key=editor_key, on_change=save_adjustments,
               disabled=[column for column in displayed if column != 'Adjustment (periods)'],
               column_config={
                   'Adjustment (periods)': st.column_config.NumberColumn('Adjustment (periods)', step=1, required=True, help='Signed whole periods added to or subtracted from the minimum.'),
                   'Required minutes': st.column_config.NumberColumn(format='%.2f'),
                   'Balance minutes': st.column_config.NumberColumn(format='%.2f', help='Actual minus required minutes. Negative means a shortfall.')},
               hide_index=True, width='stretch')
if allocation_error:
    st.error(allocation_error + ' Correct the adjustment above, or reset adjustments.')
    st.stop()
shortfalls = displayed[(displayed['Requirement status'] == 'Shortfall') & displayed.Selected]
if not shortfalls.empty:
    st.warning(f'{len(shortfalls)} subject requirement(s) are below minimum after your adjustments. See the Shortfall rows and negative Balance minutes above.')
st.subheader('Weekly curriculum hours by level and stream')
st.caption('Curriculum time = allocated periods × minutes per period, summed separately for each level and stream. Hours are decimal hours; Curriculum time shows exact hours and minutes. These totals include compulsory subjects and exactly one selected option from each elective group, with rounding and your adjustments. Minimum/maximum pathway hours show the range across all independent elective choices.')
st.dataframe(totals, column_config={'Curriculum hours': st.column_config.NumberColumn(format='%.2f'),
                                  'Required minutes': st.column_config.NumberColumn(format='%.2f'),
                                  'Minimum pathway hours': st.column_config.NumberColumn(format='%.2f'),
                                  'Maximum pathway hours': st.column_config.NumberColumn(format='%.2f')},
             hide_index=True, width='stretch')

st.subheader('4. Estimated weekly layout and dismissal')
st.caption('Uses compulsory subjects and your selected electives, with adjusted periods. Other elective pathways can have different dismissal estimates; select them above to explore. Earliest dismissal is mandatory; latest dismissal is a hard limit. The estimate tries to keep dismissal times close by balancing against clock times, rather than equal period counts. Unallocated school time is not extra curriculum and needs a school activity or supervision plan. Teaching blocks are generic: subjects, teachers and rooms have not been scheduled.')
try:
    week_days, week_blocks, week_summary = estimate_week(displayed, d, a, length)
except (ValueError, TypeError, KeyError) as error:
    st.warning(f'Weekly layout unavailable: correct School Day Settings or Fixed Activities: {error}')
    st.stop()
dismissals = week_days.pivot(index=['Level', 'Stream'], columns='Day', values='Estimated dismissal').reindex(columns=['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']).reset_index()
st.write('Estimated dismissal for every level and stream')
st.dataframe(dismissals.merge(week_summary, on=['Level', 'Stream']), hide_index=True, width='stretch')
for _, row in week_summary[week_summary['Unplaced periods'] > 0].iterrows():
    st.warning(f"{row.Level} / {row.Stream}: {row['Unplaced periods']} allocated periods cannot fit before the latest dismissal limits. The layout shows only periods that fit; it is incomplete.")
week_level = st.selectbox('Level for weekly view', list(week_summary.Level.unique()), key='week_level')
week_stream = st.selectbox('Stream for weekly view', list(week_summary.loc[week_summary.Level == week_level, 'Stream']), key='week_stream')
selected_days = week_days[(week_days.Level == week_level) & (week_days.Stream == week_stream)]
selected_blocks = week_blocks[(week_blocks.Level == week_level) & (week_blocks.Stream == week_stream)].copy()
if selected_blocks.empty:
    st.info('No teaching or fixed activity blocks in this weekly layout.')
else:
    selected_blocks['Start time'] = pd.to_datetime('2000-01-01 ' + selected_blocks.Start)
    selected_blocks['End time'] = pd.to_datetime('2000-01-01 ' + selected_blocks.End)
    fig = px.timeline(selected_blocks, x_start='Start time', x_end='End time', y='Day', color='Type',
                      hover_name='Activity', hover_data={'Start': True, 'End': True, 'Start time': False, 'End time': False},
                      category_orders={'Day': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']},
                      color_discrete_map={'Teaching': '#2563eb', 'Fixed activity': '#d97706', 'Unallocated school time': '#94a3b8'},
                      title=f'{week_level} / {week_stream} — illustrative week ({length}-minute periods)')
    fig.update_xaxes(tickformat='%H:%M', title='Time of day')
    fig.update_yaxes(autorange='reversed', title='')
    fig.update_layout(legend_title_text='Time use')
    st.plotly_chart(fig, width='stretch')
st.dataframe(selected_days, hide_index=True, width='stretch')
with st.expander('Exact weekly blocks'):
    st.dataframe(selected_blocks[['Day', 'Start', 'End', 'Type', 'Activity']], hide_index=True, width='stretch')
