from hashlib import sha256
import streamlit as st
import importlib
import simulator

# A running Cloud worker can retain the previous helper module after a code update.
# Refresh it when the new UI needs a function absent from that loaded copy.
if not all(hasattr(simulator, name) for name in (
    'sample_data', 'template', 'read_inputs', 'parse_choices',
    'custom_template', 'curriculum_allocation',
)):
    simulator = importlib.reload(simulator)

from simulator import (sample_data, template, read_inputs, parse_choices, custom_template, curriculum_allocation)

st.set_page_config(page_title='School Period Length Impact Simulator', layout='wide')
st.title('School Period Length Impact Simulator')
st.caption('Version 1 · Decision support for Singapore secondary school planners')
st.info('Synthetic examples only — these are not official MOE minimums. This view calculates weekly subject periods and curriculum hours. It does not check whether those periods fit into a timetable.')
with st.expander('1. Set up your Excel template', expanded=True):
    st.write('Enter your choices below, one per line. Click outside a box after editing to update the download.')
    columns = st.columns(3)
    with columns[0]:
        level_choices = st.text_area('Levels', 'Sec 1\nSec 2\nSec 3\nSec 4', key='template_levels')
    with columns[1]:
        stream_choices = st.text_area('Streams', 'General', key='template_streams')
    with columns[2]:
        subject_choices = st.text_area('Subjects', 'English\nMathematics\nMother Tongue\nScience', key='template_subjects')
    unit_choices = st.multiselect('Units available in the template', ['minutes', 'periods'], default=['minutes', 'periods'], key='template_units')
    st.caption('Only minutes and periods are supported. The first selected unit is prefilled; change it per row in Excel.')
    try:
        template_bytes = custom_template(parse_choices(level_choices), parse_choices(stream_choices), parse_choices(subject_choices), unit_choices)
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
    st.caption('Enter a Stream for every subject row (for example G1, G2 or G3). Enter a separate full set of subjects for each stream. School day settings and fixed activities are retained for future outputs; they do not affect the curriculum-hours calculation below. Use HH:MM times. Each level needs Monday–Friday. Fixed activities are mandatory, must lie within the day, and cannot overlap. Add as many activity rows as needed in the third sheet.')
    edited = []
    for name, frame in zip(['Subject Requirements', 'School Day Settings', 'Fixed Activities'], inputs):
        st.subheader(name)
        edited.append(st.data_editor(frame, num_rows='dynamic', key=f'input_{name}_{upload.file_id if upload else "sample"}', width='stretch'))
s, d, a = edited
st.subheader('3. Subject periods and weekly curriculum time')
length = st.select_slider('Minutes per period', options=[15, 20, 30, 35], value=30, key='period_length')
st.caption('Minimum periods = required weekly minutes ÷ minutes per period, rounded up separately for each subject. Period-based requirements use the reference duration in your input.')
try:
    base, _ = curriculum_allocation(s, length)
except (ValueError, TypeError, KeyError) as error:
    st.error(f'Please correct subject requirements: {error}')
    st.stop()

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
    displayed, totals = curriculum_allocation(s, length, adjustments)
except ValueError as error:
    allocation_error = str(error)
    displayed = base.copy()
    displayed['Adjustment (periods)'] = [adjustments[identity] for identity in identities]
    for column in ['Allocated periods', 'Actual minutes', 'Balance minutes', 'Requirement status']:
        displayed[column] = None

input_signature = sha256(s.to_json(orient='split').encode()).hexdigest()[:16]
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
shortfalls = displayed[displayed['Requirement status'] == 'Shortfall']
if not shortfalls.empty:
    st.warning(f'{len(shortfalls)} subject requirement(s) are below minimum after your adjustments. See the Shortfall rows and negative Balance minutes above.')
st.subheader('Weekly curriculum hours by level and stream')
st.caption('Curriculum time = allocated periods × minutes per period, summed separately for each level and stream. Hours are decimal hours; Curriculum time shows exact hours and minutes. These totals include rounding and your adjustments.')
st.dataframe(totals, column_config={'Curriculum hours': st.column_config.NumberColumn(format='%.2f'),
                                  'Required minutes': st.column_config.NumberColumn(format='%.2f')},
             hide_index=True, width='stretch')
