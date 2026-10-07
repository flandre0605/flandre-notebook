"""Build a dependency-free Android preview APK with the official SDK tools.

Usage: python scripts/build_android.py --sdk PATH --java-home PATH
The SDK needs platforms/android-35 and build-tools/35.0.0. No server credentials.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def build(sdk, java_home, checks=False):
    sdk, java_home = Path(sdk).resolve(), Path(java_home).resolve()
    tools = sdk / 'build-tools/35.0.0'
    library = sdk / 'platforms/android-35/android.jar'
    java = java_home / 'bin/java.exe'
    javac = java_home / 'bin/javac.exe'
    for path in (library, java, javac, tools / 'aapt2.exe', tools / 'lib/d8.jar', tools / 'lib/apksigner.jar'):
        if not path.is_file():
            raise SystemExit(f'Missing SDK/JDK tool: {path}')
    work = ROOT / 'build/android-preview'
    if work.exists():
        resolved = work.resolve()
        if resolved != work.absolute() or not resolved.is_relative_to((ROOT / 'build').resolve()):
            raise SystemExit('Unsafe Android build directory')
        shutil.rmtree(resolved)
    for name in ('classes', 'dex', 'resources', 'generated'):
        (work / name).mkdir(parents=True, exist_ok=True)
    source = ROOT / 'android/app/src/main'
    def run(*arguments):
        subprocess.run([str(a) for a in arguments], check=True, cwd=ROOT)
    run(tools / 'aapt2.exe', 'compile', '--dir', source / 'res', '-o', work / 'resources')
    run(tools / 'aapt2.exe', 'link', '-I', library, '--manifest', source / 'AndroidManifest.xml',
        '-A', source / 'assets', '--java', work / 'generated', '-o', work / 'unsigned.apk', *sorted((work / 'resources').glob('*.flat')))
    sources = sorted((source / 'java').rglob('*.java')) + sorted((work / 'generated').rglob('*.java'))
    run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-classpath', library,
        '-d', work / 'classes', *sources)
    run(java, '-cp', tools / 'lib/d8.jar', 'com.android.tools.r8.D8', '--min-api', '26',
        '--lib', library, '--output', work / 'dex', *sorted((work / 'classes').rglob('*.class')))
    with zipfile.ZipFile(work / 'unsigned.apk', 'a', compression=zipfile.ZIP_DEFLATED) as apk:
        for path in sorted((work / 'dex').glob('*.dex')):
            apk.write(path, path.name)
    run(tools / 'zipalign.exe', '-f', '-p', '4', work / 'unsigned.apk', work / 'aligned.apk')
    key = ROOT / 'build/android-preview-debug.keystore'
    # Development-only signing key, outside tracked source. Preserve across builds
    # so installing a newer preview does not require deleting private phone data.
    if not key.exists():
        run(java_home / 'bin/keytool.exe', '-genkeypair', '-keystore', key, '-storepass', 'android',
            '-keypass', 'android', '-alias', 'androiddebugkey', '-dname', 'CN=Flandre Android Preview',
            '-keyalg', 'RSA', '-keysize', '2048', '-validity', '3650', '-noprompt')
    version = ET.parse(source / 'AndroidManifest.xml').getroot().attrib['{http://schemas.android.com/apk/res/android}versionName']
    output = ROOT / f'dist/Flandre-Android-{version}.apk'
    output.parent.mkdir(parents=True, exist_ok=True)
    run(java, '-jar', tools / 'lib/apksigner.jar', 'sign', '--ks', key, '--ks-key-alias', 'androiddebugkey',
        '--ks-pass', 'pass:android', '--key-pass', 'pass:android', '--out', output, work / 'aligned.apk')
    run(java, '-jar', tools / 'lib/apksigner.jar', 'verify', '--verbose', output)
    run(tools / 'aapt.exe', 'dump', 'badging', output)
    print(f'Android preview: {output}')
    if checks:
        test = work / 'checks'
        for name in ('classes','dex'):
            (test / name).mkdir(parents=True,exist_ok=True)
        run(tools / 'aapt2.exe','link','-I',library,'--manifest',ROOT / 'android/checks/AndroidManifest.xml',
            '-o',test / 'unsigned.apk')
        run(javac,'-encoding','UTF-8','-source','8','-target','8','-classpath',
            str(library)+';'+str(work / 'classes'),'-d',test / 'classes',
            *sorted((ROOT / 'android/checks/java').rglob('*.java')))
        run(java,'-cp',tools / 'lib/d8.jar','com.android.tools.r8.D8','--min-api','26','--lib',library,
            '--classpath',work / 'classes','--output',test / 'dex',*sorted((test / 'classes').rglob('*.class')))
        with zipfile.ZipFile(test / 'unsigned.apk','a',compression=zipfile.ZIP_DEFLATED) as apk:
            for path in sorted((test / 'dex').glob('*.dex')):
                apk.write(path,path.name)
        run(tools / 'zipalign.exe','-f','-p','4',test / 'unsigned.apk',test / 'aligned.apk')
        run(java,'-jar',tools / 'lib/apksigner.jar','sign','--ks',key,'--ks-key-alias','androiddebugkey',
            '--ks-pass','pass:android','--key-pass','pass:android','--out',test / 'checks.apk',test / 'aligned.apk')
        print(f'Android instrumentation: {test / "checks.apk"}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sdk', required=True)
    parser.add_argument('--java-home', required=True)
    parser.add_argument('--checks',action='store_true')
    arguments = parser.parse_args()
    build(arguments.sdk, arguments.java_home, arguments.checks)
