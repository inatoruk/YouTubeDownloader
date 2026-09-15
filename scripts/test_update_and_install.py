"""Filesystem transaction tests without building, signing or launching software."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('installer',Path(__file__).with_name('update_and_install.py'))
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.src=self.root/'new.app';self.src.mkdir();(self.src/'payload').write_text('new')
        self.target=self.root/'Applications/YoutubeDownloader.app';self.target.mkdir(parents=True);(self.target/'payload').write_text('old')
        self.backup=self.root/'backups/run'
    def fake_run(self,*args):
        if str(args[0]).endswith('ditto'):shutil.copytree(args[-2],args[-1],symlinks=True)
        elif str(args[0]).endswith('diff'):self.assertEqual((Path(args[-2])/'payload').read_bytes(),(Path(args[-1])/'payload').read_bytes())
    def test_success_retains_old_version(self):
        with patch.object(installer,'run',side_effect=self.fake_run):result=installer.install(self.src,self.target,self.backup)
        self.assertEqual((self.target/'payload').read_text(),'new')
        self.assertEqual((self.backup/'YoutubeDownloader.app/payload').read_text(),'old')
        self.assertEqual((Path(result['staging'])/'previous.app/payload').read_text(),'old')
    def test_failed_post_install_verification_restores_old(self):
        def fail(*args):
            if str(args[0]).endswith('codesign') and args[-1]==self.target:raise RuntimeError('injected verification failure')
            self.fake_run(*args)
        with patch.object(installer,'run',side_effect=fail),self.assertRaises(RuntimeError):installer.install(self.src,self.target,self.backup)
        self.assertEqual((self.target/'payload').read_text(),'old')
    def test_staging_failure_leaves_old(self):
        with patch.object(installer,'run',side_effect=RuntimeError('copy failure')),self.assertRaises(RuntimeError):installer.install(self.src,self.target,self.backup)
        self.assertEqual((self.target/'payload').read_text(),'old')
    def test_symlink_target_rejected(self):
        target=self.root/'link.app';target.symlink_to(self.target)
        with self.assertRaises(RuntimeError):installer.install(self.src,target,self.backup)
        self.assertEqual((self.target/'payload').read_text(),'old')
if __name__=='__main__':unittest.main()
