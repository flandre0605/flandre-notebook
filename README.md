# Flandre Notebook

Flandre Notebook 是面向 Windows 和 Android 的个人错题管理与学习应用，集题目整理、AI 图片识题、练习复习和英语单词学习于一体。应用以本地数据为基础，可离线管理题库，并通过账号在电脑与手机之间同步题目、图片、单词和作答记录。

## 主要功能

- **题库管理**：新增、编辑、搜索和筛选题目，支持选择题选项、答案解析、个人笔记、标签与图片附件。
- **AI 图片识题**：电脑截图或导入图片，手机拍照、选图和裁剪；识别结果经核对后收录，未完成草稿可恢复。
- **练习与复习**：按学科、错题或到期范围练习，支持判分、自评、掌握程度记录与复习间隔设置。
- **英语单词学习**：TXT/CSV 导入、AI 补全释义与例句、翻卡、拼写练习和系统语音朗读。
- **学习统计**：作答历史、正确率、学科统计与学习热力图。
- **跨端同步**：按账号隔离数据，自动同步学习内容，支持离线补传、手动同步与冲突处理。
- **数据交换与备份**：JSON/CSV 导入导出、公式打印和 ZIP 备份恢复。
- **桌面体验**：系统托盘、截图快捷键和桌宠小窗练习。

## 下载安装

在 [GitHub Releases](https://github.com/flandre0605/flandre-notebook/releases) 下载对应平台的安装包与校验文件。

- **Windows**：完整解压免安装 ZIP，运行 `FlandreNotebook/FlandreNotebook.exe`，无需安装 Python。
- **Android**：支持 Android 8.0 及以上，下载 APK 安装。升级使用相同签名的安装包覆盖安装。

首次启动为空题库，可以直接手动录题并练习。AI 功能需要在设置中配置自己的模型服务，识题模型需支持图片输入。模型配置支持 OpenAI 兼容接口与可选的 DeepSeek 网页版接入。

## 从源码运行

桌面端使用 Python 3.10 及以上和 PySide6。在 Windows 项目目录执行：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe main.py
```

### Windows 构建

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-build.txt
.venv/Scripts/python.exe -m app.services.deepseek_web
.venv/Scripts/python.exe scripts/build_windows.py
```

构建脚本包含固定版本的 DeepSeek 网页服务，产物位于 `dist/`。生成安装器时，通过 `--iscc` 指定 Inno Setup 编译器路径。

### Android 构建

Android 客户端使用原生 Java，构建需要 JDK 17、Android SDK `platforms;android-35` 和 `build-tools;35.0.0`，无需 Gradle。

```powershell
python scripts/build_android.py --sdk <SDK目录> --java-home <JDK目录>
```

签名文件位于 `%LOCALAPPDATA%/FlandreNotebook/signing/android-preview.keystore`，使用别名 `androiddebugkey` 和开发口令 `android`；构建脚本也支持从原 `build/android-preview-debug.keystore` 迁移。首次构建需准备自己的开发签名，已发布应用的更新需使用原签名。签名文件不提交到仓库。

## 数据与模型

Windows 本机学习数据默认保存在 `%LOCALAPPDATA%/FlandreNotebook/data`，账号空间使用独立目录；可在应用设置中查看实际位置，或用 `FLANDRE_DATA_DIR` 指定独立目录。Android 数据保存在应用私有目录。

API Key 和登录凭据由系统凭据机制保护，不随题库备份或云端学习数据导出。启用 AI 识题或单词补全后，相关内容会发送至所配置的模型服务。DeepSeek 网页版使用非官方接口，其可用性取决于上游服务。

云端同步需要可用的 CloudBase 环境及对应数据库、存储权限配置；部署脚本位于 `cloud/sql/`。Windows 与 Android 的 ZIP 备份格式分别用于各自平台，跨端交换使用账号同步或 JSON/CSV。建议定期保留独立备份，AI 生成的题目和答案应人工核对。

## 项目结构

| 目录 | 内容 |
| --- | --- |
| `app/` | 桌面界面、题库与单词数据库、模型服务和同步逻辑 |
| `android/` | Android 客户端、离线公式资源与设备检查 |
| `assets/` | 应用图标、桌宠素材、界面资源与导入模板 |
| `cloud/sql/` | CloudBase 数据库与同步部署脚本 |
| `checks/` | 功能检查与测试数据 |
| `scripts/` | Windows、Android 构建与预览工具 |
| `packaging/` | 打包配置、安装器与第三方许可声明 |
| `tools/` | 云端登录及权限验证工具 |

第三方组件的来源与许可见 [许可声明](packaging/THIRD_PARTY_NOTICES.txt) 及各组件随附的许可证。
