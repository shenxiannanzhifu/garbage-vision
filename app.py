"""Streamlit 中文入口：上传、预览和模型实际状态。"""
import streamlit as st
from garbage_vision.images import decode_image

st.set_page_config(page_title="识废 · 垃圾识别实验室", page_icon="♻", layout="wide")
st.markdown("""<style>
.block-container {max-width:1240px;padding-top:2.4rem;}
h1 {letter-spacing:-1px;font-weight:750!important;}
[data-testid="stFileUploader"] {background:white;border:1px solid #d9e4dc;border-radius:16px;padding:16px;}
.eyebrow {font-size:13px;letter-spacing:3px;color:#12745b;font-weight:700;}
</style><p class="eyebrow">VISION LAB / 同图对照实验</p>""", unsafe_allow_html=True)
st.title("让每一件废弃物，找到去处。")
st.write("上传一张图片，观察视觉模型与多模态大模型如何识别与分类。")
st.caption("可回收物 · 有害垃圾 · 厨余垃圾 · 其他垃圾　｜　无法判断时保留不确定性")
uploaded = st.file_uploader("选择待识别图片", type=["jpg", "jpeg", "png", "webp"], help="最大 12 MB / 2400 万像素")
if uploaded:
    try:
        source = decode_image(uploaded.getvalue())
        st.image(source.image, caption="原图 · 已校正拍摄方向", width=620)
        st.caption(f"图片标识：{source.image_id[:16]} · {source.image.width} × {source.image.height}")
    except ValueError as exc:
        st.error(str(exc))
left,right = st.columns(2)
with left:
    st.subheader("01  本地视觉模型")
    st.info("模型准备中。当前版本仅完成图片上传与预览。")
with right:
    st.subheader("02  多模态大模型")
    st.info("尚未配置图像理解 API。")
st.divider()
st.caption("识废 · AI 第二阶段项目　/　v0.1.0　/　分类建议需结合当地规则")
