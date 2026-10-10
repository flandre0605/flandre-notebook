from pathlib import Path
import os
import importlib.metadata
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
source = Path(os.environ['FLANDRE_DEEPSEEK_SOURCE'])
data = [(str(source / name), name) for name in ('static', 'templates', 'wasm')]
data += [(str(source / 'LICENSE'), '.')]
data += collect_data_files('deepseek_tokenizer')
for distribution in importlib.metadata.distributions():
    data += copy_metadata(distribution.metadata['Name'])
analysis = Analysis([str(root / 'packaging/deepseek_entry.py')], pathex=[str(source)],
    datas=data, binaries=collect_dynamic_libs('wasmtime'),
    hiddenimports=collect_submodules('uvicorn'), excludes=['playwright'],
    hookspath=[], runtime_hooks=[], noarchive=False)
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True,
    name='FlandreDeepSeek', debug=False, strip=False, upx=False, console=True)
bundle = COLLECT(executable, analysis.binaries, analysis.datas, strip=False, upx=False,
    name='FlandreDeepSeek')
