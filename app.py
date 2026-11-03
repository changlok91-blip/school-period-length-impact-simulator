import pandas as pd
import plotly.express as px
import streamlit as st
from simulator import (sample_data, template, read_inputs, calculate, workbook, ASSUMPTIONS, DAYS, clock)

st.set_page_config(page_title='School Period Length Impact Simulator', layout='wide')
st.title('School Period Length Impact Simulator')
st.caption('Version 1 · Decision support for Singapore secondary school planners')
st.info('Synthetic examples only — these are not official MOE minimums. Dismissal times are estimates; this application does not generate or validate a subject timetable.')
st.download_button('Download Excel input template', template(), 'school_period_input_template.xlsx')
upload = st.file_uploader('Upload completed template', type=['xlsx'])
if upload:
    try:
        inputs = read_inputs(upload)
    except Exception as e:
        st.error(f'Cannot read workbook: {e}')
        st.stop()
else:
    inputs = sample_data()
with st.expander('Edit inputs', expanded=True):
    st.caption('Enter a Stream for every subject row (for example G1, G2 or G3). Enter a separate full set of subjects for each stream. School day settings and fixed activities apply to all streams in the same level. Use HH:MM times. Each level needs Monday–Friday. Fixed activities are mandatory, must lie within the day, and cannot overlap. Add as many activity rows as needed in the third sheet.')
    edited = []
    for name, frame in zip(['Subject Requirements', 'School Day Settings', 'Fixed Activities'], inputs):
        st.subheader(name)
        edited.append(st.data_editor(frame, num_rows='dynamic', key=f'input_{name}_{upload.file_id if upload else "sample"}', width='stretch'))
s, d, a = edited
try:
    base = calculate(s, d, a)
except (ValueError, TypeError, KeyError) as e:
    st.error(f'Please correct inputs: {e}')
    st.stop()
with st.expander('Override allocated whole periods (optional)'):
    st.caption('Each scenario is independently editable. Reset to automatic allocation by unchecking the option. Negative balances indicate unmet subject requirements.')
    use_overrides = st.checkbox('Use manual allocations')
    allocation = base['Subject Calculations'][['Period length', 'Level', 'Stream', 'Subject', 'Allocated periods']]
    manual = st.data_editor(allocation, disabled=['Period length', 'Level', 'Stream', 'Subject'], hide_index=True, column_config={'Allocated periods': st.column_config.NumberColumn(min_value=0, step=1)}, key='manual_allocations')
try:
    overrides = {(r['Period length'], r['Level'], r['Stream'], r['Subject']): r['Allocated periods'] for _, r in manual.iterrows()} if use_overrides else None
    results = calculate(s, d, a, overrides)
except ValueError as e:
    st.error(str(e))
    st.stop()
level = st.selectbox('Level to display', ['All levels'] + list(s.Level.unique()))
stream = st.selectbox('Stream to display', ['All streams'] + (list(s.loc[s.Level == level, 'Stream'].unique()) if level != 'All levels' else list(s.Stream.unique())))
def view(frame):
    result = frame if level == 'All levels' else frame[frame.Level == level]
    result = result.copy() if stream == 'All streams' else result[result.Stream == stream].copy()
    result['Level / Stream'] = result.Level + ' / ' + result.Stream
    return result
comparison = view(results['Comparison'])
st.subheader('Four-scenario comparison')
st.caption('Capacity and demand are calculated separately for each level and stream. All streams of a level use the same school day settings; their demand is never added together. Actual minutes reflect allocated periods, including any that cannot fit.')
st.dataframe(comparison, hide_index=True, width='stretch')
st.plotly_chart(px.bar(comparison, x='Period length', y='Minimum periods', color='Level / Stream', barmode='group', text_auto=True, title='Minimum weekly teaching periods required by level'), width='stretch')
length = st.select_slider('Scenario for detailed charts', options=[15, 20, 30, 35], value=30)
detail = view(results['Subject Calculations'])
selected = detail[detail['Period length'] == length]
heat = selected.pivot(index='Subject', columns='Level / Stream', values='Balance minutes')
fig = px.imshow(heat, text_auto=True, color_continuous_scale='RdBu', color_continuous_midpoint=0, labels={'color': 'Minutes'}, title='Subject balance: negative = shortfall; positive = excess', aspect='auto')
st.plotly_chart(fig, width='stretch')
st.subheader('Estimated Monday–Friday dismissal')
st.caption('Teaching periods are distributed as evenly as daily capacities permit, then packed from the start of teaching windows. Mandatory fixed activities may determine dismissal even when lessons finish earlier. No filler teaching is added to reach the preferred earliest dismissal.')
daily = view(results['Dismissal Estimates'])
selected_daily = daily[daily['Period length'] == length]
fig = px.line(selected_daily, x='Day', y='Dismissal minute', color='Level / Stream', markers=True, text='Estimated dismissal', category_orders={'Day': DAYS}, hover_data=['Assigned periods', 'Capacity periods', 'Status'], title=f'Estimated dismissal — {length}-minute periods')
ticks = list(range(360, 1440, 60))
fig.update_yaxes(tickvals=ticks, ticktext=[clock(x) for x in ticks], title='Estimated time (24-hour)')
st.plotly_chart(fig, width='stretch')
st.dataframe(selected_daily.drop(columns='Dismissal minute'), hide_index=True, width='stretch')
st.subheader('Warnings')
warnings = view(results['Warnings'])
if warnings.empty:
    st.success('No capacity, dismissal-window or subject-shortfall warnings.')
else:
    for _, row in warnings.iterrows():
        st.warning(f"{row['Period length']} min · {row.Level} / {row.Stream}: {row.Warning}")
st.caption('Late dismissal cannot occur within the hard latest-time capacity model. A capacity shortage means teaching remains unplaced; extending the school day would require changing its settings.')
st.subheader('Detailed subject requirements — all four scenarios')
st.dataframe(detail, hide_index=True, width='stretch')
with st.expander('Calculation assumptions and limitations'):
    for item in ASSUMPTIONS.Assumption:
        st.write('• ' + item)
st.download_button('Download complete results (all levels and scenarios)', workbook({'Input Assumptions': ASSUMPTIONS, 'Subject Requirements': s, 'School Day Settings': d, 'Fixed Activities': a, **results}), 'school_period_results.xlsx')
