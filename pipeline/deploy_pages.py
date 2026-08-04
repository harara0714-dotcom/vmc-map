"""生成したvmc_map.png/htmlをGitHub Pagesへ公開する。

2つの実行環境をサポートする:
- ローカルMac: gh_pages_site(このリポジトリのローカルclone)へコピーし、
  git commit&pushする(個人の実メールアドレスがcommit authorに出ないよう、
  gh_pages_siteのgit設定にはGitHubのnoreplyアドレスを使うこと。セットアップ済み)。
- GitHub Actions (GITHUB_ACTIONS=true): git操作はせず、VMC_CI_SITE_DIR環境変数で
  指定されたステージングフォルダへコピーするだけ。実際の公開はワークフロー側の
  actions/deploy-pagesが行う。ワークフロー開始時に現在公開中のサイトを
  ステージングフォルダへ復元しておくことで、このrunで生成されなかったファイル
  (例: 気象データ取得失敗でVMCマップ本体を更新できなかった回)は前回公開分が
  そのまま維持される。
"""

import glob
import os
import shutil
import subprocess

import config


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def _copy_artifacts(out_dir, site_dir, map_png_path, map_html_path):
    """out_dir配下の生成物をsite_dirへコピーする(git操作は別途)。"""
    os.makedirs(site_dir, exist_ok=True)

    if map_png_path is not None:
        shutil.copy(map_png_path, os.path.join(site_dir, "vmc_map.png"))
    if map_html_path is not None:
        shutil.copy(map_html_path, os.path.join(site_dir, "index.html"))

    fbjp_reference = os.path.join(out_dir, "fbjp_reference.png")
    if os.path.exists(fbjp_reference):
        shutil.copy(fbjp_reference, os.path.join(site_dir, "fbjp_reference.png"))

    theta_e_map = os.path.join(out_dir, "theta_e_850hpa.png")
    if os.path.exists(theta_e_map):
        shutil.copy(theta_e_map, os.path.join(site_dir, "theta_e_850hpa.png"))

    elevation_map = os.path.join(out_dir, "elevation_map.png")
    if os.path.exists(elevation_map):
        shutil.copy(elevation_map, os.path.join(site_dir, "elevation_map.png"))

    gsi_relief_map = os.path.join(out_dir, "gsi_relief_map.png")
    if os.path.exists(gsi_relief_map):
        shutil.copy(gsi_relief_map, os.path.join(site_dir, "gsi_relief_map.png"))

    for combo_path in glob.glob(os.path.join(out_dir, "gsi_relief_sigwx_ft*.png")):
        shutil.copy(combo_path, os.path.join(site_dir, os.path.basename(combo_path)))

    for ft in config.LOW_LEVEL_SIGWX_FTS:
        dirname = config.sigwx_region_dirname(ft)
        sigwx_src_dir = os.path.join(out_dir, dirname)
        if not os.path.isdir(sigwx_src_dir):
            continue
        sigwx_dest_dir = os.path.join(site_dir, dirname)
        os.makedirs(sigwx_dest_dir, exist_ok=True)
        for name in os.listdir(sigwx_src_dir):
            shutil.copy(os.path.join(sigwx_src_dir, name), os.path.join(sigwx_dest_dir, name))


def _deploy_local(out_dir, map_png_path, map_html_path):
    """変更があればコミット&プッシュし、Trueを返す。変更が無ければFalse。"""
    site_dir = config.GH_PAGES_DIR
    if not os.path.isdir(os.path.join(site_dir, ".git")):
        raise RuntimeError(f"{site_dir} はgitリポジトリではありません(初期セットアップが必要)")

    _copy_artifacts(out_dir, site_dir, map_png_path, map_html_path)

    _run(["git", "add", "-A"], cwd=site_dir)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=site_dir)
    if diff.returncode == 0:
        return False  # 変更なし

    _run(["git", "commit", "-m", "Update VMC map"], cwd=site_dir)
    _run(["git", "push", config.GH_PAGES_REMOTE, config.GH_PAGES_BRANCH], cwd=site_dir)
    return True


def _deploy_ci(out_dir, map_png_path, map_html_path):
    """GitHub Actions上でのステージングフォルダへのコピーのみ(git操作なし)。"""
    site_dir = os.environ.get("VMC_CI_SITE_DIR")
    if not site_dir:
        raise RuntimeError("VMC_CI_SITE_DIR が未設定です(ワークフロー側の設定漏れ)")
    _copy_artifacts(out_dir, site_dir, map_png_path, map_html_path)
    return True


def deploy(out_dir, map_png_path=None, map_html_path=None):
    """変更があればコミット&プッシュ(またはCIステージングへコピー)し、Trueを返す。

    map_png_path/map_html_pathを省略した場合、VMCマップ本体(vmc_map.png/index.html)は
    更新せず前回公開分のまま維持する(気象データ取得に失敗した回でも、標高図・
    下層悪天オーバーレイなど気象に依存しない画像だけは常に最新化するため)。
    """
    if not config.GH_PAGES_ENABLED:
        return False

    if os.environ.get("GITHUB_ACTIONS") == "true":
        return _deploy_ci(out_dir, map_png_path, map_html_path)
    return _deploy_local(out_dir, map_png_path, map_html_path)
