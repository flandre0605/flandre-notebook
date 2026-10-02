# 芙兰朵露主题应用图标

设计元素：金发红瞳、白色帽饰与红缎带、彩色水晶翼、手持笔记本。采用深红圆角底板和透明外边缘，适用于错题本窗口与侧栏。

- `flandre_icon.png`：1254 × 1254，RGBA 透明原图。
- `flandre_icon.ico`：16、24、32、48、64、128、256 像素七种尺寸，用于 Qt 应用窗口，也可在后续打包时作为 EXE 图标。
- `main.py` 使用 ICO 设置应用窗口图标，`app/ui/main_window.py` 使用 PNG 显示侧栏品牌图标。
- 素材通过内置 `image_gen` 工具生成；ICO 为同一素材的格式导出，没有新增运行依赖。

## 生成提示词

```text
Use case: logo-brand. Asset type: a polished Windows desktop app icon for a personal study notebook. Create ONE square icon, not an icon sheet, not a mockup. Subject: an adorable chibi Flandre Scarlet from Touhou, recognizable short golden blonde hair, vivid ruby-red eyes, white frilled mob cap with a bold red ribbon, a small red outfit, distinctive dark branching wing stems carrying eight large faceted rainbow crystal diamonds (four per side). She is holding a simple small cream-colored notebook at the bottom center, linking the mascot to a study app. Composition: large centered head and face, close portrait filling most of a ruby/crimson rounded-square tile; wing crystals hug the upper-left and upper-right silhouette, with the hat, face and notebook dominant. Entire tile fully inside the square with modest transparent margin; real transparent alpha outside the tile. Style: expertly designed flat vector-like anime mascot emblem, bold clean dark plum contours, broad solid color blocks, a little restrained cel shading, friendly expression, balanced symmetry, no intricate hair strands. Palette: crimson red, warm ivory, golden blonde and small jewel-colored accents; tile softly shaded deep crimson. Legible and recognizable as a 32px desktop icon. Avoid text, lettering, logos, watermarks, multiple icons, mockup shadows, photorealism, detailed scene backgrounds, unnecessary tiny decorations.
```

