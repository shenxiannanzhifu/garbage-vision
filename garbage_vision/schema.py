"""本地与 API 方案共用的结果结构；明确类别、未知状态及不同分数的意义。"""
from typing import Literal
from datetime import datetime,timezone
from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal['recyclable', 'hazardous', 'kitchen', 'other']

class Item(BaseModel):
    """单个物品；坐标为方向校正后的原图像素 XYXY，API 不强行提供框。"""
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    category: Category | None = None
    reason: str = Field(min_length=1, max_length=1000)
    uncertain: bool = False
    label: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    detection_confidence: float | None = Field(default=None, ge=0, le=1)
    mask_quality: float | None = None
    similarity: float | None = Field(default=None, ge=-1, le=1)
    category_margin: float | None = None
    visual_similarity: float | None = Field(default=None,ge=-1,le=1)
    visual_margin: float | None = None
    classification_basis: Literal['text','visual_reference'] = 'text'

    @model_validator(mode='after')
    def check_uncertainty(self):
        """未知保留空类别，不能默认为其他垃圾。"""
        if self.category is None:
            self.uncertain = True
        if self.uncertain and self.category is not None:
            raise ValueError('不确定物品必须使用 category=null')
        if self.bbox:
            x1,y1,x2,y2=self.bbox
            if min(x1,y1)<0 or x2<=x1 or y2<=y1:
                raise ValueError('检测框坐标无效')
        return self

class InferenceResult(BaseModel):
    """一次真实运行的审计信息；失败也是结果，评估时不删除失败图片。"""
    model_config = ConfigDict(extra='forbid')
    schema_version: str = '1.0'
    created_at_utc: str = Field(default_factory=lambda:datetime.now(timezone.utc).isoformat())
    image_id: str
    source_sha256: str
    image_size: tuple[int,int]
    method: Literal['local','api']
    model: str
    status: Literal['success','error','not_configured']
    items: list[Item] = Field(default_factory=list)
    elapsed_seconds: float = 0
    load_seconds: float = 0
    cache_hit: bool = False
    error: str | None = None
    metadata: dict = Field(default_factory=dict)

    @property
    def categories(self) -> set[str]:
        """共同计分单位为确定的四分类出现集合；未知和错误不自动记对。"""
        return {x.category for x in self.items if x.category is not None} if self.status=='success' else set()
