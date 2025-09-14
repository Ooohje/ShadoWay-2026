# streamlit_app/app.py
import streamlit as st
from ui import render_app

# set_page_config는 반드시 첫 Streamlit 호출 이전!
st.set_page_config(
    page_title="ShadoWay",
    page_icon="🌤️",
    layout="wide",
)

render_app()
