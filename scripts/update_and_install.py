"""Build in isolation, verify, and install with rollback. Never delete backups."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tarfile
import stat

ROOT = Path(__file__).resolve().parent.parent


def run(*args):
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True)


def install(source, target, backup_root):
    """Stage and verify before renaming; keep the former app for rollback."""
    if target.is_symlink():
        raise RuntimeError('Refusing a symbolic-link destination')
    target.parent.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(tempfile.mkdtemp(prefix='.YoutubeDownloader-stage-', dir=target.parent))
    staged = stage_dir / 'YoutubeDownloader.app'
    run('/usr/bin/ditto', '--norsrc', '--noextattr', '--noacl', source, staged)
    for entry in [staged, *staged.rglob('*')]:
        if not entry.is_symlink() and entry.stat().st_flags & stat.UF_HIDDEN:
            os.chflags(entry, entry.stat().st_flags & ~stat.UF_HIDDEN)
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', staged)
    backup = backup_root / 'YoutubeDownloader.app'
    existed = target.exists()
    if existed:
        backup_root.mkdir(parents=True, exist_ok=False)
        run('/usr/bin/ditto', '--norsrc', '--noextattr', '--noacl', target, backup)
        run('/usr/bin/diff', '-qr', target, backup)
    previous = stage_dir / 'previous.app'
    if existed:
        target.rename(previous)
    try:
        staged.rename(target)
        run('/usr/bin/codesign', '--verify', '--deep', '--strict', target)
    except BaseException:
        if target.exists():
            target.rename(stage_dir / 'failed.app')
        if previous.exists():
            previous.rename(target)
        raise
    # Retain stage/previous as well; deletion is deliberately left to the user.
    return {'destination': str(target), 'backup': str(backup) if existed else None,
            'staging': str(stage_dir), 'launch_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-update', action='store_true', help='Keep installed yt-dlp')
    parser.add_argument('--build-only', action='store_true', help='Do not install')
    parser.add_argument('--destination', type=Path, default=Path('/Applications/YoutubeDownloader.app'))
    args = parser.parse_args()
    target = args.destination.expanduser().absolute()
    if target.name != 'YoutubeDownloader.app':
        parser.error('Destination must end in YoutubeDownloader.app')
    python = ROOT/'.venv/bin/python'
    for tool in ['ffmpeg', 'codesign', 'ditto']:
        if shutil.which(tool) is None:
            parser.error(f'Missing tool: {tool}')
    # A successful PyInstaller exit is not enough: Qt introspection may fail.
    run(python, '-c', "from PySide6.QtCore import QLibraryInfo; from pathlib import Path; p=Path(QLibraryInfo.path(QLibraryInfo.PluginsPath))/'platforms/libqcocoa.dylib'; assert p.is_file(), 'Missing Qt cocoa plugin: '+str(p)")
    if not args.skip_update:
        run(python, '-m', 'pip', 'install', '--upgrade', 'yt-dlp')
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    # Keep temporary files for diagnosis; neither current build nor dist is overwritten.
    work = Path(tempfile.mkdtemp(prefix='ytd-build-'))
    env = os.environ.copy()
    env['PYINSTALLER_CONFIG_DIR'] = str(work/'cache')
    subprocess.run([str(python), '-m', 'PyInstaller', '--clean', '--noconfirm',
                    '--workpath', str(work/'work'), '--distpath', str(work/'dist'),
                    str(ROOT/'YoutubeDownloader.spec')], cwd=ROOT, env=env, check=True)
    app = work/'dist/YoutubeDownloader.app'
    # Finder hidden flags can make Qt silently skip otherwise present plugins.
    # Normalize only the new artifact, never the dependency environment.
    for entry in [app, *app.rglob('*')]:
        if not entry.is_symlink() and entry.stat().st_flags & stat.UF_HIDDEN:
            os.chflags(entry, entry.stat().st_flags & ~stat.UF_HIDDEN)
    if not any(app.rglob('libqcocoa.dylib')):
        raise RuntimeError('Build is missing the cocoa Qt platform plugin; refusing installation')
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', app)
    release = ROOT/'dist/releases'/stamp
    release.mkdir(parents=True, exist_ok=False)
    # Sync services can add forbidden resource forks to .app directories.
    # Preserve the verified app in an archive; install directly from clean temp.
    built = app
    archive = release/'YoutubeDownloader.app.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        bundle.add(app, arcname='YoutubeDownloader.app')
    version = subprocess.check_output([str(python), '-c',
        'import sys,PyInstaller,yt_dlp.version;print(sys.version);print(PyInstaller.__version__);print(yt_dlp.version.__version__)'],text=True)
    result = {'release':str(archive),'verified_app':str(built),'work':str(work),'versions':version,
              'launch_verified':False,'installed':False}
    if not args.build_only:
        result.update(install(built, target, ROOT/'dist/backups'/stamp))
        result['installed'] = True
    (release/'build-record.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    print('署名検証済み。起動・ダウンロードの確認は別途必要です。旧版は自動削除しません。')


if __name__ == '__main__':
    main()
