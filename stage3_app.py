"""三阶段网页：上传→HTTP任务→轮询数据库结果；页面不直接执行模型。"""
import json
from uuid import uuid4
import httpx
import streamlit as st
from garbage_vision.config import ROOT, rules
from garbage_vision.images import decode_image
from garbage_vision.schema import InferenceResult
from garbage_vision.service_client import request

st.set_page_config(page_title='识废 · 三阶段服务',page_icon='♻',layout='wide')
st.title('识废 · 同图双方案')
st.caption('三阶段 · 页面通过后端创建任务，结果保存后可再次查看。模型输出仅供分类实验。')
names=rules()['categories']


def show_task(task):
    st.caption(f"任务：{task['id']} ｜ 状态：{task['status']} ｜ 创建时间（UTC）：{task['created_at']}")
    st.caption(f"原图哈希：{task['source_sha256']} ｜ 规范图片哈希：{task['image_id']}")
    if task.get('error'):st.warning(task['error'])
    try:
        st.image(request('GET',f"/v1/tasks/{task['id']}/image").content,width=500,caption='本任务原图（已校正方向）')
    except (httpx.HTTPError,RuntimeError) as exc:st.warning(str(exc))
    for method,column,title in zip(['local','api'],st.columns(2),['01 本地模型','02 多模态大模型']):
        with column:
            st.subheader(title)
            st.write('状态：'+task[method+'_status'])
            raw=task.get('results',{}).get(method)
            if not raw:
                if method=='api' and task['api_status']=='skipped':st.info('此任务未调用大模型。')
                continue
            result=InferenceResult.model_validate(raw)
            st.caption(f'{result.model} ｜ 推理/请求 {result.elapsed_seconds:.2f}秒 ｜ 加载 {result.load_seconds:.2f}秒')
            if result.status!='success':st.error(result.error or '识别失败');continue
            if result.metadata.get('fallback'):st.warning(result.metadata['fallback'])
            if method=='local':
                picture=request('GET',f"/v1/tasks/{task['id']}/annotated").content
                st.image(picture,caption='分割区域有框；整图回退没有定位，不用于精确计数',width='stretch')
                st.download_button('下载标注图',picture,file_name=task['id']+'.png',mime='image/png',key='png-'+task['id'],on_click='ignore')
            if not result.items:st.info('未给出足够确定的物品；不代表图片里没有垃圾。')
            else:
                st.dataframe([{'物品':x.name,'类别':names.get(x.category,'无法确定'),'依据':x.reason,
                    '定位':'分割区域' if x.bbox else '未定位','相似度':x.similarity} for x in result.items],hide_index=True,width='stretch')
            with st.expander('模型记录（来自已保存结果）'):
                st.json({k:v for k,v in result.metadata.items() if k!='response_text'})
    results=task.get('results',{})
    if all(results.get(k,{}).get('status')=='success' for k in ['local','api']):
        a,b=(InferenceResult.model_validate(results[k]).categories for k in ['local','api'])
        st.write('共同类别：'+('、'.join(names[k] for k in sorted(a&b)) or '无'))
        st.caption('类别重合或差异不代表哪一侧一定正确。')
    for fmt,column in zip(['json','csv'],st.columns(2)):
        body=request('GET',f"/v1/tasks/{task['id']}/export",params={'format':fmt}).content
        column.download_button('下载 '+fmt.upper(),body,file_name=task['id']+'.'+fmt,
            mime='application/json' if fmt=='json' else 'text/csv',key=fmt+'-'+task['id'],on_click='ignore')


try:
    ready=request('GET','/health/ready').json()
except (httpx.HTTPError,RuntimeError) as exc:
    st.error('后端暂不可用，请先启动三阶段服务。'+str(exc));st.stop()
with st.expander('服务与模型说明'):
    st.write('默认模型仍为 SAM2.1 tiny＋CLIP ViT-B/32；相似度不是准确率，未知不会默认分到其他垃圾。')
    st.write('任务在单实例后台顺序执行，最多等待8项；重启后中断任务保留状态，不自动重新识别。')
    st.json(ready)
if not ready['ready_for_tasks']:st.error('后端缺少默认模型权重，请检查部署。')

mode=st.radio('选择操作',['新建任务','任务历史'],horizontal=True)
if mode=='新建任务':
    uploaded=st.file_uploader('选择图片',type=['jpg','jpeg','png','webp'],help='最大12MB / 2400万像素')
    selected=''
    manifest=ROOT/'data/manifests/dev.json'
    examples=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
    examples=[r for r in examples if (ROOT/r['path']).exists()]
    with st.expander('使用开发样例（已用数据，不是新的测试集）'):
        selected=st.selectbox('样例',['']+[r['id'] for r in examples])
        if selected:
            row=next(r for r in examples if r['id']==selected)
            st.caption(f"{row['title']} ｜ {row['author']} ｜ {row['license']}")
            st.markdown(f"[来源与许可]({row['source_page']})")
    data=uploaded.getvalue() if uploaded else (ROOT/next(r['path'] for r in examples if r['id']==selected)).read_bytes() if selected else None
    source=None
    if data:
        try:source=decode_image(data)
        except ValueError as exc:st.error(str(exc))
    similarity=st.slider('本地相似度下限',.20,.40,.28,.01)
    manual_paid=ready.get('paid_calls_mode')=='manual'
    paid_label='同时运行大模型：向服务商发送本图并按实际用量计费' if manual_paid else '同时运行大模型：向服务商发送本图，消耗一次已批准次数并可能计费'
    paid=st.checkbox(paid_label,False,
                     disabled=not ready['paid_calls_enabled'])
    if manual_paid:st.caption('已取消测试次数上限。仅在你勾选并创建任务时调用；查看历史不收费。')
    identity=(source.source_sha256 if source else None,similarity,paid)
    if st.session_state.get('s3_identity')!=identity:
        st.session_state['s3_identity']=identity
        st.session_state.pop('s3_current',None)
        st.session_state.pop('s3_completed',None)
        st.session_state['s3_submission_key']=str(uuid4())
    current=st.session_state.get('s3_current')
    if source:st.image(source.image,width=450,caption='待上传图片')
    if st.button('创建识别任务',type='primary',disabled=not source or bool(current)):
        try:
            response=request('POST','/v1/tasks',files={'file':('upload.bin',data)},
                data={'include_api':str(paid).lower(),'similarity_min':str(similarity)},
                headers={'Idempotency-Key':st.session_state['s3_submission_key']})
            st.session_state['s3_current']=response.json()['id'];st.rerun()
        except (httpx.HTTPError,RuntimeError) as exc:
            st.error(str(exc));st.info('若响应中断，再点一次会复用同一提交编号，避免重复创建任务。')
    if st.session_state.get('s3_current'):
        @st.fragment(run_every=None if st.session_state.get('s3_completed') else '2s')
        def poll():
            try:
                task=request('GET','/v1/tasks/'+st.session_state['s3_current']).json()
                show_task(task)
                if task['status'] in {'queued','running'}:st.info('任务等待或执行中，此页面只查询，不会重复调用模型。')
                elif not st.session_state.get('s3_completed'):
                    st.session_state['s3_completed']=True
                    st.rerun()
            except (httpx.HTTPError,RuntimeError) as exc:st.error(str(exc))
        poll()
        if st.button('明确开始另一项任务'):
            st.session_state.pop('s3_current',None);st.session_state.pop('s3_completed',None)
            st.session_state['s3_submission_key']=str(uuid4());st.rerun()
else:
    page=st.number_input('页码',min_value=1,value=1,step=1)
    try:
        tasks=request('GET','/v1/tasks',params={'limit':20,'offset':(page-1)*20}).json()['tasks']
        if not tasks:st.info('暂无记录。')
        else:
            selected=st.selectbox('选择已保存任务',[t['id'] for t in tasks],
                format_func=lambda v:next(t['created_at']+' ｜ '+t['status']+' ｜ '+v[:8] for t in tasks if t['id']==v),key='s3_history_id')
            st.info('此处读取数据库中的历史结果，不发送新的识别请求。')
            task=request('GET','/v1/tasks/'+selected).json();show_task(task)
            confirm=st.checkbox('确认删除该任务图片和结果（不会删除其他任务，也不会退回已预留调用次数）')
            if st.button('删除本任务',disabled=not confirm or task['status'] in {'queued','running'}):
                request('DELETE','/v1/tasks/'+selected);st.rerun()
    except (httpx.HTTPError,RuntimeError) as exc:st.error(str(exc))
