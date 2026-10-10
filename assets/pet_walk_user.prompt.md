# 用户提供的完整走路帧

- 原图：`pet_walk_user.original.png`，用户提供，1024×765，四列两行、八个完整姿势。
- 使用图：`pet_walk_user.png`，内置 imagegen 透明处理输出，1451×1084；保留生成的 alpha。原图单独保留。
- 程序按从左到右、从上到下切帧，80 毫秒一帧，640 毫秒一轮。仅平移对齐帽顶，不拆分、旋转、拼接或重新绘制肢体。
- 在实际桌面背景上检查边缘和白色前景；极低 alpha 的隐藏彩色像素在原始透明图查看器里可能明显，实际合成显示正常。

## 最终透明处理提示词（内置 imagegen）

Use case: background-extraction / cutout repair. Image 1 is the ORIGINAL and authoritative user-selected eight-pose sprite atlas, white background, 4 columns and 2 rows. Image 2 is a FAILED transparency extraction of it: it introduced RED scattered speckles, red noisy halos, detached fragments, white edge pixels and has uneven edges. Correct the extraction. Return an exact clean cutout of IMAGE 1 with actual transparent background, keeping all eight original illustrations, exact poses, colors, original proportions and row-major 4x2 layout. Remove ALL detached red/colored speckles and stray pixels in the space between sprites. CLEAN EDGE CRITICAL: outside the original dark character outlines alpha must be exactly zero, with only a 1-pixel smooth antialias boundary. No colored haze or noise around any edge, no white halo, no transparency holes inside the hats or clothes. Every white bonnet, sleeve, frill, sock and highlight inside original outline stays opaque. Follow original image contours accurately including thin dark wings and crystals. Do not redraw or regenerate anatomy or alter any joint, pose, character or gesture. No checkerboard, ground, added pixels or decorative effects. Output the original 1024x765 (or 1024x768) 4-column 2-row atlas as clean RGBA transparent PNG. Each sprite must be a coherent cutout, with no floating debris. The original image has no red marks outside the characters: do not hallucinate them.
