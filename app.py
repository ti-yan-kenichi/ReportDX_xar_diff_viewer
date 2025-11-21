import streamlit as st
import pandas as pd

st.title("Hello, Streamlit!")
df = pd.DataFrame({"x":[1,2,3], "y":[3,1,2]})
st.line_chart(df, x="x", y="y")