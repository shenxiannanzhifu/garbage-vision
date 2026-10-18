# 真实GPU页面逻辑回归

当前配置通过Streamlit AppTest执行，API未启用。commons-701056为荧光灯，有真实SAM区域框并归有害；commons-26461093为香蕉皮，归厨余且明确整图识别无框。塑料瓶及坏图/换图由48项完整检查覆盖。

这里的PNG是模型标注图，不是浏览器截图或视频。首次回归两图均通过；进程退出时发生Windows沙箱临时目录清理警告，随后为验证脚本加入与测试相同的可选临时目录兼容处理并重新运行。

## 图片来源和署名

- commons-701056.png：File:Spiral fluorescent lamp.jpg；作者 Alphax；CC BY 2.5。来源：https://commons.wikimedia.org/wiki/File:Spiral_fluorescent_lamp.jpg。许可：https://creativecommons.org/licenses/by/2.5。处理：方向校正/转换RGB，荧光灯图叠加模型区域框及中文标签。
- commons-26461093.png：File:Banane-A-05 cropped.jpg；作者 Priwo；Public domain。来源：https://commons.wikimedia.org/wiki/File:Banane-A-05_cropped.jpg。许可：。处理：方向校正/转换RGB，荧光灯图叠加模型区域框及中文标签。
