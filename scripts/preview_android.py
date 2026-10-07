"""Build and open the real Android app in a local emulator; optionally watch edits."""
import argparse
import msvcrt
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'android/app/src/main'
AVD_NAME = 'flandre-preview'
SERIAL = 'emulator-5570'


def fingerprint():
    paths = [p for p in SOURCE.rglob('*') if p.is_file()]
    paths.append(ROOT / 'scripts/build_android.py')
    return tuple((str(p.relative_to(ROOT)), p.stat().st_mtime_ns, p.stat().st_size)
                 for p in sorted(paths))


def apk_path():
    version = ET.parse(SOURCE / 'AndroidManifest.xml').getroot().attrib[
        '{http://schemas.android.com/apk/res/android}versionName']
    return ROOT / f'dist/Flandre-Android-{version}.apk'


def java_home(value):
    if value:
        return Path(value).resolve()
    for candidate in (os.environ.get('JAVA_HOME'), 'H:/jdk17/jdk-17.0.12'):
        if candidate and (Path(candidate) / 'bin/javac.exe').is_file():
            return Path(candidate).resolve()
    javac = shutil.which('javac')
    if javac:
        return Path(javac).resolve().parent.parent
    raise RuntimeError('找不到 JDK 17，请通过 --java-home 指定已安装的 JDK。')


def build(sdk, java):
    log = ROOT / 'build/android-preview-build.log'
    print('正在更新电脑预览……', flush=True)
    with log.open('wb') as out:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/build_android.py'),
                                 '--sdk', str(sdk), '--java-home', str(java)],
                                cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
    if result.returncode:
        print(log.read_text(encoding='utf-8', errors='replace')[-4000:], flush=True)
        raise RuntimeError(f'构建失败，已保留原预览。详细记录：{log}')


def adb(sdk, *args, check=True, timeout=30):
    return subprocess.run([str(sdk / 'platform-tools/adb.exe'), '-s', SERIAL, *args],
                          check=check, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout)


def prepare_avd(sdk):
    image = sdk / 'system-images/android-35/default/x86_64'
    if not (image / 'system.img').is_file():
        raise RuntimeError('缺少 Android 35 模拟器镜像，请先安装项目使用的 SDK 系统镜像。')
    avd_home = ROOT / 'build/android-avd'
    directory = avd_home / f'{AVD_NAME}.avd'
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / 'config.ini'
    if not config.exists():
        config.write_text(f'''avd.ini.encoding=UTF-8
hw.cpu.arch=x86_64
hw.cpu.ncore=2
hw.ramSize=2048
hw.lcd.width=393
hw.lcd.height=852
hw.lcd.density=160
hw.gpu.enabled=yes
hw.gpu.mode=swiftshader
image.sysdir.1={image}
tag.id=default
disk.dataPartition.size=6442450944
hw.keyboard=yes
hw.camera.back=virtualscene
hw.camera.front=none
hw.mainKeys=no
showDeviceFrame=no
''', encoding='utf-8')
    (avd_home / f'{AVD_NAME}.ini').write_text(
        f'avd.ini.encoding=UTF-8\npath={directory}\ntarget=android-35\n', encoding='utf-8')
    return avd_home


def open_emulator(sdk):
    avd_home = prepare_avd(sdk)
    env = {**os.environ, 'ANDROID_AVD_HOME': str(avd_home), 'ANDROID_HOME': str(sdk)}
    running = adb(sdk, 'get-state', check=False)
    if running.returncode == 0:
        if adb(sdk, 'emu', 'avd', 'name').stdout.splitlines()[0].strip() != AVD_NAME:
            raise RuntimeError('预览端口被其他模拟器占用，请关闭它后再打开预览。')
    else:
        log = (ROOT / 'build/android-preview-emulator.log').open('ab')
        try:
            subprocess.Popen([str(sdk / 'emulator/emulator.exe'), '-avd', AVD_NAME,
                              '-port', '5570', '-no-audio', '-no-boot-anim',
                              '-no-snapshot-load', '-no-snapshot-save', '-gpu', 'swiftshader'],
                             cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        finally:
            log.close()
    print('正在打开安卓预览窗口（第一次启动会稍慢）……', flush=True)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if adb(sdk, 'shell', 'getprop', 'sys.boot_completed', check=False).stdout.strip() == '1':
            return
        time.sleep(1)
    raise RuntimeError('模拟器未能启动，请查看 build/android-preview-emulator.log。')


def install(sdk):
    apk = apk_path()
    if not apk.is_file():
        raise RuntimeError(f'缺少安装包：{apk}')
    adb(sdk, 'install', '-r', str(apk), timeout=120)
    adb(sdk, 'shell', 'am', 'start', '-W', '-n', 'com.flandre.notebook/.MainActivity')
    print('预览已更新，模拟器题库保留。', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, default=ROOT / 'build/android-sdk')
    parser.add_argument('--java-home')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--no-build', action='store_true', help='Open the existing APK first.')
    args = parser.parse_args()
    sdk = args.sdk.resolve()
    java = java_home(args.java_home)
    for tool in ('platform-tools/adb.exe', 'emulator/emulator.exe'):
        if not (sdk / tool).is_file():
            raise RuntimeError(f'缺少 SDK 工具：{sdk / tool}')
    (ROOT / 'build').mkdir(exist_ok=True)
    # One watcher owns this preview; no changes to connected physical phones.
    with (ROOT / 'build/android-preview.lock').open('a+b') as lock:
        if lock.seek(0, 2) == 0:
            lock.write(b'0');lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print('电脑预览已经在运行，请使用已打开的模拟器窗口。', flush=True)
            return
        observed = fingerprint()
        if not args.no_build:
            build(sdk, java)
        open_emulator(sdk)
        install(sdk)
        if args.watch:
            print('已开启自动预览更新：保存安卓源码后自动更新模拟器。关闭模拟器或按 Ctrl+C 结束。', flush=True)
            while True:
                time.sleep(1)
                current = fingerprint()
                if current != observed:
                    time.sleep(.5)
                    current = fingerprint()
                    try:
                        build(sdk, java)
                        install(sdk)
                    except (RuntimeError, subprocess.CalledProcessError) as error:
                        print(str(error), flush=True)
                    observed = current
                elif adb(sdk, 'get-state', check=False).returncode:
                    return


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        main()
    except KeyboardInterrupt:
        print('自动更新已停止。')
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
