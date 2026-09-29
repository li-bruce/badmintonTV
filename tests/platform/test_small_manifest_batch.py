"""Small imports keep registry checks batched and retain hash-time identities."""
import hashlib
import json

from test_api import setup
from packages.contracts import TRAINING_REGISTRY_PATH, UsageScopeGuard


def test_small_manifest_reads_registry_per_batch_not_per_asset(setup,monkeypatch):
    client,app,base,library,root=setup
    registry=root/TRAINING_REGISTRY_PATH
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({'schema_version':'1.0','assets':[
        {'asset_id':f'training-{i}','relative_path':f'data/training/{i}.mp4',
         'sha256':f'{i+1000:064x}','usage_scope':'training_only'} for i in range(500)]}))
    assets=[]; identities={}
    for i in range(20):
        raw=f'synthetic small manifest {i}'.encode()
        relative=f'data/batch-{i}.mp4'; path=root/relative
        path.write_bytes(raw)
        value={**base,'asset_id':f'batch-{i}','relative_path':relative,
               'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        assets.append(value)
        identities[value['asset_id']]=app.state.store._file_identity(path)
    calls=[]; original=UsageScopeGuard._registry
    def counted(self):
        calls.append(True)
        return original(self)
    monkeypatch.setattr(UsageScopeGuard,'_registry',counted)
    response=client.post('/api/v1/assets/import',json={'library_id':library['library_id'],'manifest':{'assets':assets}})
    assert response.status_code==200,response.text
    assert len(response.json()['imported'])==20
    assert len(calls)<=3  # Declared batch, actual batch, and Store transaction preflight.
    with app.state.store.connect() as db:
        rows=db.execute("SELECT asset_id,identity FROM source_identities WHERE asset_id LIKE 'batch-%'").fetchall()
    assert {row[0]:json.loads(row[1]) for row in rows}==identities


def test_small_manifest_batch_still_checks_actual_training_digest_before_import(setup):
    client,app,base,library,root=setup
    raw=b'synthetic registered training bytes'
    path=root/'data/renamed-training.mp4';path.write_bytes(raw)
    registry=root/TRAINING_REGISTRY_PATH;registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({'schema_version':'1.0','assets':[{
        'asset_id':'training-original','relative_path':'data/training/synthetic.mp4',
        'sha256':hashlib.sha256(raw).hexdigest(),'usage_scope':'training_only'}]}))
    declared={**base,'asset_id':'renamed-training','relative_path':'data/renamed-training.mp4',
              'sha256':'f'*64,'size_bytes':len(raw)}
    response=client.post('/api/v1/assets/import',json={'library_id':library['library_id'],'manifest':{'assets':[declared]}})
    assert response.status_code==422 and 'TRAINING_ONLY' in response.text,response.text
    assert [row['asset_id'] for row in app.state.store._raw_assets()]==[base['asset_id']]
