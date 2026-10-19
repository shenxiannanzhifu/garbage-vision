"""中文网页：同一图片的独立推理、错误隔离与结果导出。"""
import json
import time
from dataclasses import replace
import streamlit as st
from garbage_vision.config import ROOT, local_settings, rules, fingerprint
from garbage_vision.images import decode_image
from garbage_vision.local import infer_local
from garbage_vision.api import api_settings, infer_api, PROMPT_PATH
from garbage_vision.schema import InferenceResult
from garbage_vision.saved_results import find_saved_api
from garbage_vision.exports import annotate, export_json, export_csv

st.set_page_config(page_title='识废 · 垃圾识别实验室', page_icon='♻', layout='wide')
st.markdown('''<style>
.block-container{max-width:1240px;padding-top:2.4rem;}
h1{letter-spacing:-1px;font-weight:750!important;}
[data-testid="stFileUploader"]{background:white;border:1px solid #d9e4dc;border-radius:16px;padding:16px;}
.eyebrow{font-size:13px;letter-spacing:3px;color:#12745b;font-weight:700;}
</style><p class="eyebrow">VISION LAB / 同图对照实验</p>''', unsafe_allow_html=True)
st.title('让每一件废弃物，找到去处。')
st.write('上传图片，查看物品定位、分类依据与两种方案的差异。')
st.caption('可回收物 · 有害垃圾 · 厨余垃圾 · 其他垃圾　｜　无法判断时保留不确定性')
taxonomy=rules(); names=taxonomy['categories']; settings=local_settings()
with st.expander('识别范围与实验设置'):
    st.write('按北京生活垃圾四分类口径，假定主体已决定丢弃。饮料瓶先倒空清洁，食物先分离包装。灯具类型、化学残留等不能只靠图片保证。')
    st.write('本地方案：SAM2 分割 + CLIP 区域及上下文分类。无法定位时可能提供整图分类并明确标注。小物品、遮挡、堆积仍可能漏检或错分，不能精确计数。')
    settings['similarity_min']=st.slider('本地分类相似度下限',.20,.40,float(settings['similarity_min']),.01)
    st.caption('相似度不是准确率。修改阈值会清空旧结果；正式评估使用冻结配置。')
uploaded=st.file_uploader('选择待识别图片',type=['jpg','jpeg','png','webp'],help='最大 12 MB / 2400 万像素')
manifest=ROOT/'data/manifests/dev.json'
examples=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
examples=[r for r in examples if (ROOT/r['path']).exists()]
with st.expander('使用开发样例（含困难和失败场景）'):
    selected=st.selectbox('样例图片',['']+[r['id'] for r in examples],format_func=lambda value:'请选择' if not value else next(r['title'].removeprefix('File:') for r in examples if r['id']==value))
    if selected:
        row=next(r for r in examples if r['id']==selected)
        st.caption(f"作者：{row['author']} · {row['license']}")
        st.markdown(f"[原图及许可来源]({row['source_page']})")
        st.caption('开发样例不能作为未见测试结果；上传图片时优先使用上传文件。')
source=None
try:
    data=uploaded.getvalue() if uploaded else (ROOT/next(r['path'] for r in examples if r['id']==selected)).read_bytes() if selected else None
    if data is not None:source=decode_image(data)
except (ValueError,OSError) as exc:
    st.error(str(exc))
try:
    api_config=api_settings(); api_problem=api_config.problem()
    # 关闭调用开关不等于丢失密钥，避免已配置的用户被引导重复填密钥。
    if not api_config.enabled:
        setup_problem=replace(api_config,enabled=True).problem()
        api_problem=setup_problem or 'API 已完成本地配置；网页新请求当前暂停，已保存结果仍可查看。'
except (ValueError,TypeError):
    api_config=None; api_problem='API 配置中的数字或业务空间 ID 无效，请检查本地 .env。'
# 换图、错误上传、修改规则或阈值后清空旧结果，防止图 A 的预测显示在图 B 下。
identity=(source.image_id,source.source_sha256) if source else None
run_key=fingerprint({'image':identity,'local':settings,'rules':taxonomy,'api_model':api_config.model if api_config else '',
    'api_base':api_config.base_url if api_config else '',
    'api_options':{k:getattr(api_config,k) for k in ['provider','max_tokens','reasoning_effort','image_detail','image_transport']} if api_config else {},
    'aliases':(ROOT/settings['text_aliases']).read_text(encoding='utf-8') if settings.get('text_aliases') else '',
    'prompt':(ROOT/PROMPT_PATH).read_text(encoding='utf-8')})
if st.session_state.get('run_key')!=run_key:
    st.session_state['run_key']=run_key; st.session_state['results']={}
if source:
    st.image(source.image,caption='原图 · 已校正拍摄方向',width=620)
    st.caption(f'图片标识：{source.image_id[:16]} · {source.image.width} × {source.image.height}')
    include_api=st.checkbox('同时运行大模型（向配置的服务商发送本图，可能产生费用）',value=False,disabled=bool(api_problem))
    saved_api=find_saved_api(source,api_config)
    if saved_api and st.button('查看本图已保存的大模型实测（不收费）',key='saved_api'):
        st.session_state['results']['api']=saved_api
    if st.button('开始识别',type='primary',key='run'):
        for method in (['local','api'] if include_api else ['local']):
            started=time.perf_counter()
            with st.spinner('本地模型正在加载或识别…' if method=='local' else '大模型正在识别同一张图片…'):
                try:
                    result=infer_local(source,settings) if method=='local' else infer_api(source,api_config)
                except (RuntimeError,OSError,ValueError,ImportError) as exc:
                    message='本地模型运行失败，请检查权重、依赖及设备。' if method=='local' else 'API 运行失败，请检查本地配置。'
                    if isinstance(exc,FileNotFoundError):message='缺少模型权重，请运行 scripts/download_weights.py。'
                    result=InferenceResult(image_id=source.image_id,source_sha256=source.source_sha256,image_size=source.image.size,
                        method=method,model='SAM2 + CLIP' if method=='local' else api_config.model,status='error',error=message,
                        elapsed_seconds=time.perf_counter()-started,metadata={'error_type':type(exc).__name__})
                st.session_state['results'][method]=result

def render_result(result):
    """页面与导出共用同一结果，不重新猜测类别。"""
    if result.status!='success':st.error(result.error);return
    if result.metadata.get('display_mode')=='saved_real_api_result':
        st.info(f'已保存的真实 API 结果，本次没有发送请求。原调用时间（UTC）：{result.created_at_utc}')
    st.caption(f'{result.model} · 推理/请求 {result.elapsed_seconds:.2f} 秒 · 加载 {result.load_seconds:.2f} 秒')
    if result.metadata.get('fallback'):st.warning(result.metadata['fallback'])
    if result.method=='local':
        picture=annotate(source,result);st.image(picture,caption='有框项来自分割区域；整图识别项没有定位框，不保证精确计数',width='stretch')
        if result.metadata.get('image_fallback_used'):st.info('部分结果来自整图识别，未获得可靠定位。请查看清单中的“定位方式”。')
        st.download_button('下载本地标注图',picture,file_name=f'{source.image_id[:12]}-annotated.png',mime='image/png')
    if not result.items:st.info('未识别到足够确定的支持范围内物品。这不代表图片里没有垃圾。')
    else:
        rows=[]
        for index,item in enumerate(result.items,1):
            row={'序号':index,'物品':item.name,'四分类':names.get(item.category,'无法确定'),'依据 / 不确定项':item.reason}
            if result.method=='local':row.update({'定位方式':'分割区域' if item.bbox else '整图识别，未定位','分割质量':round(item.mask_quality,3) if item.mask_quality is not None else None,'分类相似度':round(item.similarity,3) if item.similarity is not None else None})
            rows.append(row)
        st.dataframe(rows,hide_index=True,width='stretch')
    with st.expander('本次实验记录'):
        st.json({'image_id':result.image_id,'缓存命中':result.cache_hit,**{k:v for k,v in result.metadata.items() if k!='response_text'}})

left,right=st.columns(2); results=st.session_state.get('results',{})
with left:
    st.subheader('01  本地视觉模型')
    if 'local' in results and source:render_result(results['local'])
    else:st.info('本地模型已接入。选择图片后点击“开始识别”。')
with right:
    st.subheader('02  多模态大模型')
    if api_config:st.caption(f'当前模型：{api_config.model} · 服务商：{api_config.provider}')
    if 'api' in results and source:render_result(results['api'])
    else:st.info(api_problem or 'API 已配置，尚未调用。勾选“同时运行大模型”后点击开始。')
    if not api_problem:
        st.caption('每次由你勾选并点击“开始识别”后发送图片，按服务商计费；失败不会自动重试。')
if source and results:
    valid=list(results.values())
    if all(k in results and results[k].status=='success' for k in ['local','api']):
        local_c,api_c=results['local'].categories,results['api'].categories
        st.write('共同识别类别：'+('、'.join(names[x] for x in sorted(local_c&api_c)) or '无'))
        st.write('仅本地识别：'+('、'.join(names[x] for x in sorted(local_c-api_c)) or '无')+'；仅大模型识别：'+('、'.join(names[x] for x in sorted(api_c-local_c)) or '无'))
        st.caption('这里只显示差异；没有人工真值时不能据此断言哪一侧正确。')
    a,b=st.columns(2)
    a.download_button('导出 JSON 实验记录',export_json(valid),file_name=f'{source.image_id[:12]}.json',mime='application/json')
    b.download_button('导出 CSV 清单',export_csv(valid),file_name=f'{source.image_id[:12]}.csv',mime='text/csv')
st.divider();st.caption('识废 · 本地质量已复评，NexaVLinks / GPT-6 Astra 已完成小样验证　/　模型输出仅供分类实验')
