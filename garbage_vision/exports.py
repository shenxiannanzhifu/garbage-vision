"""把同一结果导出为 JSON、CSV 和中文标注图片；不添加模型未给出的定位。"""
import csv
from io import BytesIO, StringIO
import json
from pathlib import Path
from PIL import ImageDraw, ImageFont
from .config import rules

COLORS={'recyclable':'#1775c9','hazardous':'#c84242','kitchen':'#16825b','other':'#666666',None:'#bd7b13'}

def annotate(source,result):
    """在原始 RGB 图片上画真实框；API 没有框时返回原图。"""
    if result.image_id!=source.image_id:raise ValueError('结果与当前图片不匹配')
    canvas=source.image.copy();draw=ImageDraw.Draw(canvas)
    size=max(14,min(30,canvas.width//40))
    candidates=[Path('C:/Windows/Fonts/msyh.ttc'),Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    font_path=next((p for p in candidates if p.exists()),None)
    font=ImageFont.truetype(str(font_path),size) if font_path else ImageFont.load_default(size=size)
    for i,item in enumerate(result.items,1):
        if not item.bbox:continue
        color=COLORS[item.category];x1,y1,x2,y2=item.bbox
        draw.rectangle(item.bbox,outline=color,width=max(2,size//8))
        label=f'{i} {item.name}' if font_path else f'{i} {item.label or item.category or "unknown"}'
        box=draw.textbbox((0,0),label,font=font);w,h=box[2]-box[0],box[3]-box[1]+8
        x=min(max(0,x1),max(0,canvas.width-w-8));y=max(0,y1-h)
        draw.rectangle((x,y,x+w+8,y+h),fill=color)
        draw.text((x+4,y+2-box[1]),label,font=font,fill='white')
    out=BytesIO();canvas.save(out,format='PNG');return out.getvalue()

def export_json(results):
    """包含成功、失败、配置指纹和图片标识，便于审计同图比较。"""
    return json.dumps({'results':[x.model_dump() for x in results]},ensure_ascii=False,indent=2).encode('utf-8')

def safe_cell(value):
    """CSV 在 Excel 打开时禁止外部模型文本成为公式。"""
    text=str(value if value is not None else '')
    return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r')) else text

def export_csv(results):
    buffer=StringIO(newline='')
    writer=csv.writer(buffer);writer.writerow(['图片标识','方案','状态','物品','四分类','原因','分割质量','余弦相似度','耗时秒'])
    names=rules()['categories']
    for result in results:
        if not result.items:writer.writerow([result.image_id,result.method,result.status,'','',safe_cell(result.error),'','',result.elapsed_seconds])
        for item in result.items:
            writer.writerow([result.image_id,result.method,result.status,safe_cell(item.name),names.get(item.category,'无法确定'),safe_cell(item.reason),item.mask_quality,item.similarity,result.elapsed_seconds])
    return buffer.getvalue().encode('utf-8-sig')
