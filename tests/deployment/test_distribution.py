"""Safety and portability tests use tiny local fixtures only."""
import importlib.util
import gc
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('deploy_manage', REPO/'scripts/deploy/manage.py')
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='btv-deploy-')
        self.base = Path(self.temp.name)

    def tearDown(self):
        gc.collect()  # shared CapacityLedger constructor holds a SQLite cycle until collection on Windows
        self.temp.cleanup()

    def args(self, **changes):
        values = dict(profile='workbench-cpu', storage_root=str(self.base), env_root=None, dev=False, dry_run=True, ffmpeg='ffmpeg', ffprobe='ffprobe')
        values.update(changes)
        return SimpleNamespace(**values)

    def repository(self):
        root = self.base/'repo'
        root.mkdir()
        subprocess.run(['git','init','-q',str(root)],check=True)
        def write(name, text):
            path=root/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(text,encoding='utf-8')
        write('deployment/modules.json', json.dumps(manage.config()))
        write('packages/contracts/__init__.py','VALUE=1\n')
        write('packages/runtime/__init__.py','VALUE=2\n')
        write('packages/render/__init__.py','from packages.contracts import VALUE\n')
        write('configs/models/taxonomy.v1.json','{}')
        write('docs/CONTRACTS.md','contracts')
        write('AGENTS.md','read docs/CONTRACTS.md')
        write('unselected.txt','not included')
        subprocess.run(['git','-C',str(root),'add','--','deployment','packages','configs','docs','AGENTS.md','unselected.txt'],check=True)
        self.commit(root)
        return root

    def commit(self, root):
        subprocess.run(['git','-C',str(root),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','fixture'],check=True)

    def test_modules_closure(self):
        self.assertEqual(manage.closure(['render'],manage.config()),['core','render'])
        self.assertNotIn('models',manage.closure(['workbench'],manage.config()))

    def test_cpu_plans_no_gpu_dependencies(self):
        for profile in ('core-cpu','library-cpu','render-cpu','workbench-cpu','desktop-cpu'):
            plan=manage.make_plan(self.args(profile=profile))
            self.assertFalse(plan['gpu'])
            self.assertFalse(plan['delegated'])
            requirement='\n'.join(line for line in Path(plan['commands'][1][-1]).read_text(encoding='utf-8-sig').splitlines() if not line.startswith('#'))
            self.assertNotIn('torch==',requirement)
            self.assertNotIn('cuda',requirement.casefold())
        self.assertNotIn('torch',sys.modules)

    def test_gpu_delegated(self):
        root=self.repository(); (root/'packages/models').mkdir(); (root/'scripts/models').mkdir(parents=True); (root/'scripts/models/setup_device.sh').write_text('#!/bin/bash\n')
        plan=manage.make_plan(self.args(profile='models-gpu'),root=root)
        self.assertTrue(plan['delegated'])
        self.assertIn('gpu-base',plan['command'])
        if os.name == 'nt':
            self.assertEqual(plan['command'][:5],['wsl.exe','-d','Ubuntu','--','bash'])
            self.assertTrue(plan['command'][5].startswith('/mnt/'))

    def test_nonroot_cwd(self):
        result=subprocess.run([sys.executable,'-B',str(REPO/'scripts/deploy/manage.py'),'plan','--storage-root',str(self.base)],cwd=self.base,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['source_root'],str(REPO))

    def test_setup_dry_run_writes_nothing(self):
        before=list(self.base.iterdir())
        manage.setup(self.args())
        self.assertEqual(list(self.base.iterdir()),before)

    def test_env_owner_escape_rejected(self):
        with self.assertRaises(ValueError): manage.make_plan(self.args(env_root=str(self.base/'outside')))

    def test_relative_storage_rejected(self):
        with self.assertRaises(ValueError): manage.make_plan(self.args(storage_root='relative'))

    def test_paths_rejected(self):
        for value in ('../x','x/../y','/tmp/x','C:/x','a\\b','a//b','a:stream','a/CON.txt','a/x.','a/x?z','a/\nx'):
            with self.subTest(value=value), self.assertRaises(ValueError): manage.safe_relative(value)

    def test_forbidden_sources(self):
        for value in ('apps/.env','apps/.env.example','packages/a.pt','docs/id_rsa','packages/file.mp4','.runtime/readme.md','packages/credentials.json','docs/file.sqlite3'):
            self.assertFalse(manage.source_allowed(value),value)

    def test_export_dependency_closed_and_verify(self):
        root=self.repository(); output=self.base/'render.zip'
        result=manage.export_source(root,'render',output)
        self.assertEqual(result['modules'],['core','render'])
        with zipfile.ZipFile(output) as archive:
            self.assertIn('packages/contracts/__init__.py',archive.namelist())
            self.assertIn('configs/models/taxonomy.v1.json',archive.namelist())
            self.assertIn('CONTINUE_DEVELOPMENT.md',archive.namelist())
            self.assertNotIn('unselected.txt',archive.namelist())
        self.assertEqual(manage.verify_archive(output)['status'],'verified')
        with self.assertRaises(ValueError): manage.export_source(root,'render',output)

    def test_dirty_tree_rejected(self):
        root=self.repository(); (root/'AGENTS.md').write_text('dirty')
        with self.assertRaises(ValueError): manage.export_source(root,'core',self.base/'dirty.zip')
        result=manage.export_source(root,'core',self.base/'trial.zip',allow_dirty=True)
        self.assertTrue(result['uncommitted'])

    def test_tracked_media_refused(self):
        root=self.repository(); (root/'packages/render/movie.mp4').write_bytes(b'not a video')
        subprocess.run(['git','-C',str(root),'add','packages/render/movie.mp4'],check=True); self.commit(root)
        with self.assertRaises(ValueError): manage.export_source(root,'render',self.base/'bad.zip')

    def test_secret_bytes_refused(self):
        root=self.repository(); (root/'packages/render/key.txt').write_text('-----BEGIN PRIVATE KEY-----\n' + 'A'*64)
        subprocess.run(['git','-C',str(root),'add','packages/render/key.txt'],check=True); self.commit(root)
        with self.assertRaises(ValueError): manage.export_source(root,'render',self.base/'bad.zip')

    def test_git_symlink_refused(self):
        root=self.repository()
        blob=subprocess.run(['git','-C',str(root),'hash-object','-w','--stdin'],input=b'../contracts',capture_output=True,check=True).stdout.decode().strip()
        subprocess.run(['git','-C',str(root),'update-index','--add','--cacheinfo','120000,'+blob+',packages/render/link.py'],check=True)
        self.commit(root)
        with self.assertRaises(ValueError): manage.export_source(root,'render',self.base/'bad.zip',allow_dirty=True)

    def test_corrupt_archive_refused(self):
        root=self.repository(); output=self.base/'good.zip'; manage.export_source(root,'core',output)
        corrupt=self.base/'corrupt.zip'
        with zipfile.ZipFile(output) as source, zipfile.ZipFile(corrupt,'w') as target:
            for item in source.infolist(): target.writestr(item, b'changed' if item.filename=='AGENTS.md' else source.read(item.filename))
        with self.assertRaises(ValueError): manage.verify_archive(corrupt)

    def state_args(self, **changes):
        storage=self.base/'data'; storage.mkdir(exist_ok=True)
        (storage/'platform').mkdir(exist_ok=True)
        values=dict(storage_root=str(storage),output=str(storage/'platform/state'),manifest=[],database=[],quiesced=False,max_bytes=2_000_000,verify_assets=False)
        values.update(changes)
        return SimpleNamespace(**values)

    def test_wal_backup_retains_committed_data(self):
        args=self.state_args(database=['state.sqlite3'])
        db=sqlite3.connect(Path(args.storage_root)/'state.sqlite3')
        try:
            db.execute('PRAGMA journal_mode=WAL'); db.execute('CREATE TABLE annotation(id INT,label TEXT)'); db.execute("INSERT INTO annotation VALUES(1,'unknown')"); db.commit()
            self.assertTrue(Path(args.storage_root,'state.sqlite3-wal').exists())
            result=manage.export_state(args); self.assertEqual(result['databases'],1)
            with closing(sqlite3.connect(Path(args.output)/'state.sqlite3')) as backup:
                self.assertEqual(backup.execute('SELECT label FROM annotation').fetchone()[0],'unknown')
            self.assertFalse(Path(args.output,'state.sqlite3-wal').exists())
            with self.assertRaises(ValueError): manage.export_state(args)
        finally: db.close()

    def test_multi_database_needs_quiescence(self):
        args=self.state_args(database=['a.db','b.db'])
        for name in args.database: sqlite3.connect(Path(args.storage_root)/name).close()
        with self.assertRaises(ValueError): manage.export_state(args)

    def test_state_manifest_only_no_media_copy(self):
        args=self.state_args(verify_assets=True)
        video=Path(args.storage_root)/'video.mp4'; video.write_bytes(b'fixture bytes')
        manifest=self.base/'manifest.json'; digest=manage.hashlib.sha256(video.read_bytes()).hexdigest()
        manifest.write_text(json.dumps({'assets':[{'asset_id':'asset-test','relative_path':'video.mp4','sha256':digest}]}))
        args.manifest=[str(manifest)]
        manage.export_state(args)
        self.assertEqual({p.name for p in Path(args.output).iterdir()},{'migration-manifest.json','source-manifests'})
        report=json.loads(Path(args.output,'migration-manifest.json').read_text())
        self.assertEqual(report['assets'][0]['source_verification'],'sha256_verified')

    def test_state_path_escape(self):
        args=self.state_args(database=['../outside.db'])
        with self.assertRaises(ValueError): manage.export_state(args)

    def test_state_budget(self):
        args=self.state_args(database=['a.db'],max_bytes=20)
        with closing(sqlite3.connect(Path(args.storage_root)/'a.db')) as db: db.execute('CREATE TABLE t(x INT)'); db.commit()
        with self.assertRaises(ValueError): manage.export_state(args)


    def test_unsafe_output_symlink(self):
        real=self.base/'real'; real.mkdir()
        link=self.base/'link'
        try:
            os.symlink(real,link,target_is_directory=True)
        except OSError:
            if os.name!='nt': raise
            subprocess.run(['powershell.exe','-NoProfile','-Command',"New-Item -ItemType Junction -Path '"+str(link)+"' -Target '"+str(real)+"' | Out-Null"],check=True)
        with self.assertRaises(ValueError): manage.no_links(link/'file.zip')

    def test_quiesced_queue_backup_closes_reservations_only_in_copy(self):
        args=self.state_args(database=['platform/runtime.sqlite3'],quiesced=True)
        from packages.runtime.storage import CapacityLedger
        ledger=CapacityLedger(Path(args.storage_root)/'platform/runtime.sqlite3',args.storage_root)
        reservation=ledger.reserve('platform',1000,job_id='test')
        try:
            manage.export_state(args)
            with closing(sqlite3.connect(Path(args.output)/'runtime.sqlite3')) as target:
                self.assertEqual(target.execute('SELECT COUNT(*) FROM reservations WHERE released_at IS NULL').fetchone()[0],0)
            with closing(sqlite3.connect(Path(args.storage_root)/'platform/runtime.sqlite3')) as source:
                self.assertEqual(source.execute('SELECT released_at FROM reservations WHERE reservation_id=?',(reservation,)).fetchone()[0],None)
        finally: ledger.release(reservation)



    def test_queued_jobs_refused_for_migration(self):
        args=self.state_args(database=['platform/runtime.sqlite3'],quiesced=True)
        from packages.runtime.queue import Queue
        queue=Queue(Path(args.storage_root)/'platform/runtime.sqlite3')
        queue.enqueue('probe',{})
        with self.assertRaisesRegex(ValueError,'runnable'): manage.export_state(args)

    def test_active_gpu_lease_refused(self):
        args=self.state_args(database=['platform/runtime.sqlite3'],quiesced=True)
        with closing(sqlite3.connect(Path(args.storage_root)/'platform/runtime.sqlite3')) as db:
            db.execute('CREATE TABLE resource_leases(status TEXT)')
            db.execute("INSERT INTO resource_leases VALUES('orphaned')")
            db.commit()
        with self.assertRaisesRegex(ValueError,'GPU lease'): manage.export_state(args)



    def test_restore_rebinds_database_on_another_path(self):
        args=self.state_args(database=['platform/runtime.sqlite3'],quiesced=True)
        from packages.runtime.queue import Queue
        source=Queue(Path(args.storage_root)/'platform/runtime.sqlite3')
        old_path=Path(args.storage_root)/'platform/platform.sqlite3'
        source.bind_business_database(old_path)
        manage.export_state(args)
        relocated=Queue(Path(args.output)/'runtime.sqlite3')
        new_path=Path(args.output)/'platform.sqlite3'
        relocated.bind_business_database(new_path)
        with source.connection() as db:
            self.assertEqual(db.execute("SELECT value FROM runtime_metadata WHERE key='business_database'").fetchone()[0],str(old_path.resolve()))
        report=json.loads(Path(args.output,'migration-manifest.json').read_text())
        self.assertTrue(report['databases'][0]['database_binding_removed_in_copy'])



    def test_bootstrap_without_site_packages(self):
        command=[sys.executable,'-S','-B','-c','import sys; sys.path.insert(0,'+repr(str(REPO))+'); from packages.runtime.storage import CapacityLedger; assert "pydantic" not in sys.modules; assert "torch" not in sys.modules']
        result=subprocess.run(command,cwd=self.base,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_capacity_scanner_does_not_follow_directory_links(self):
        from packages.runtime.storage import directory_bytes
        storage=self.base/'storage';storage.mkdir()
        outside=self.base/'outside';outside.mkdir();(outside/'large.txt').write_bytes(b'x'*1000)
        link=storage/'linked-env'
        try: os.symlink(outside,link,target_is_directory=True)
        except OSError:
            if os.name!='nt': raise
            subprocess.run(['powershell.exe','-NoProfile','-Command',"New-Item -ItemType Junction -Path '"+str(link)+"' -Target '"+str(outside)+"' | Out-Null"],check=True)
        self.assertEqual(directory_bytes(storage),0)



    def test_delegate_rejects_missing_module_and_script(self):
        root=self.repository()
        with self.assertRaisesRegex(ValueError,'lacks modules'):
            manage.make_plan(self.args(profile='models-gpu'),root=root)
        (root/'packages/models').mkdir()
        with self.assertRaisesRegex(ValueError,'setup_device.sh'):
            manage.make_plan(self.args(profile='models-gpu'),root=root)

    def test_wsl_path_conversion(self):
        self.assertEqual(manage.wsl_path('D:/video/runtime/models/envs/gpu'),'/mnt/d/video/runtime/models/envs/gpu')
        self.assertEqual(manage.wsl_path('C:/My Repo/setup.sh'),'/mnt/c/My Repo/setup.sh')
        with self.assertRaises(ValueError): manage.wsl_path('//server/share/file')

    def test_full_manifest_bytes_preserve_usage_provenance_and_pts(self):
        args=self.state_args()
        manifest=self.base/'catalog.json'
        content={'schema_version':'1.0','custom_future_field':{'unknown':None},'assets':[{'asset_id':'asset-training','relative_path':'data/training/a.mp4','sha256':'a'*64,'usage_scope':'training_only','rights':{'status':'unknown','license_url':None},'provenance':{'pts_index':{'relative_path':'data/training/a.pts.json','sha256':'b'*64},'source_url':'https://example.invalid/source'},'future_annotation':{'value':'unknown'}}]}
        raw=b'\xef\xbb\xbf'+json.dumps(content,indent=3).encode('utf-8')
        manifest.write_bytes(raw);args.manifest=[str(manifest)]
        manage.export_state(args)
        report=json.loads(Path(args.output,'migration-manifest.json').read_text())
        self.assertTrue(report['assets_are_reference_inventory_only'])
        self.assertEqual(report['assets'][0]['usage_scope'],'training_only')
        original=report['source_manifests'][0]
        self.assertEqual(Path(args.output,original['file']).read_bytes(),raw)
        self.assertEqual(original['sha256'],manage.hashlib.sha256(raw).hexdigest())

    def test_original_manifest_budget_enforced(self):
        args=self.state_args(max_bytes=10)
        manifest=self.base/'catalog.json';manifest.write_text(json.dumps({'assets':[],'large':'x'*100}))
        args.manifest=[str(manifest)]
        with self.assertRaisesRegex(ValueError,'manifests exceed'):manage.export_state(args)


if __name__=='__main__': unittest.main()
