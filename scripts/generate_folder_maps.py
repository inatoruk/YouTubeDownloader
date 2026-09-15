"""Generate small offline maps of project-owned files; omit generated internals."""
import datetime
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
NOTES={'.venv':'Python実行環境。内部一覧は省略。','.git':'Git履歴。内部一覧は省略。','build':'ビルド中間物・検証記録。内部一覧は省略。','dist':'配布アーカイブ・旧版の退避。内部一覧は省略。','docs':'操作・開発・履歴に分類した資料。','main.py':'起動入口・診断・例外処理。','qt_app.py':'画面全体と操作の接続。','downloader.py':'yt-dlpによる取得処理。','queue_manager.py':'キュー・並列処理・状態。','theme.py':'見た目の共通設定。','widgets':'画面部品。','utils':'ログ設定。','scripts':'更新・検証・構造図生成。'}
def node(p):
    n={'n':p.name,'p':p.relative_to(ROOT).as_posix(),'t':'dir' if p.is_dir() else 'file','note':NOTES.get(p.name,'')}
    skip=p.name in {'.venv','.git','build','dist'} or p.name.endswith('.app') or p.name.startswith('削除候補_')
    if p.is_dir() and not skip:
        n['c']=[node(x) for x in sorted(p.iterdir(),key=lambda x:(not x.is_dir(),x.name)) if x.name not in {'.DS_Store','__pycache__'} and not x.is_symlink()]
    elif skip:n['note']=n['note'] or '保持・手動削除待ちの生成物。内部一覧は省略。'
    return n

def main():
    data={'nodes':[node(p) for p in sorted(ROOT.iterdir(),key=lambda x:(not x.is_dir(),x.name)) if p.name not in {'.DS_Store','__pycache__'}]}
    template=(ROOT/'scripts/folder_map_template.html').read_text()
    for filename,mode in [('folder-map.html','current'),('folder-map-organized.html','proposed')]:
        html=template.replace('__DATA__',json.dumps(data,ensure_ascii=False).replace('</','<\\/')).replace('__MODE__',mode).replace('__DATE__',datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))
        (ROOT/filename).write_text(html)
        print(filename,len(html.encode()),'bytes')
if __name__=='__main__':main()
