"""Worker-owned artifact hash proofs; caller declarations never create proof."""
import hashlib
import os
import stat
from pathlib import Path


class ArtifactIdentityError(ValueError):
    pass


def file_identity(value):
    info = value if hasattr(value, 'st_size') else Path(value).stat()
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def check_identity(path, expected):
    if file_identity(path) != expected:
        raise ArtifactIdentityError('ARTIFACT_CHANGED: 产物文件身份变化，请重新生成或后台验证')


def check_proof(path, proof):
    check_identity(path, proof['identity'])
    with Path(path).open('rb') as stream:
        if file_identity(os.fstat(stream.fileno())) != proof['descriptor_identity']:
            raise ArtifactIdentityError('ARTIFACT_CHANGED: 产物文件句柄身份变化')
    check_identity(path, proof['identity'])


def hash_identity(path, *, check=None, max_bytes=None):
    """Capture identity from the same descriptor whose bytes are hashed."""
    path = Path(path)
    before = path.stat()
    identity = file_identity(before)
    if not stat.S_ISREG(before.st_mode):
        raise ArtifactIdentityError('ARTIFACT_CHANGED: 产物不是普通文件')
    if max_bytes is not None and before.st_size > max_bytes:
        raise ArtifactIdentityError('ARTIFACT_REVERIFY_REQUIRED: 旧大产物缺少可信文件身份，请重新生成或后台验证')
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        descriptor_identity = file_identity(os.fstat(stream.fileno()))
        # Windows Python can expose birth time in path stat's st_ctime but
        # change time in fd stat. Preserve both rather than dropping ctime.
        if descriptor_identity[:4] != identity[:4]:
            raise ArtifactIdentityError('ARTIFACT_CHANGED: 产物在打开时变化')
        while chunk := stream.read(1024 * 1024):
            if check:
                check()
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise ArtifactIdentityError('ARTIFACT_CHANGED: 产物校验期间超过有界读取上限')
            digest.update(chunk)
        if size != before.st_size or file_identity(os.fstat(stream.fileno())) != descriptor_identity:
            raise ArtifactIdentityError('ARTIFACT_CHANGED: 产物校验期间变化')
    check_identity(path, identity)
    return {'sha256': digest.hexdigest(), 'size_bytes': size, 'identity': identity, 'descriptor_identity': descriptor_identity}


def remember_worker_artifact(context, artifact, proof):
    if not hasattr(context, 'artifact_identities'):
        context.artifact_identities = {}
    context.artifact_identities[artifact['artifact_id']] = {**proof, 'relative_path': artifact['relative_path']}


def result_artifact_proofs(context, result):
    """Publish only this worker's verified identities, never CLI result fields."""
    from .storage import resolve_relative_path
    verified, seen = {}, set()
    for artifact in result.get('artifacts', []):
        key = artifact['artifact_id']
        if key in seen:
            raise ArtifactIdentityError('ARTIFACT_CHANGED: 重复的产物ID')
        seen.add(key)
        path = resolve_relative_path(context.storage_root, artifact['relative_path'], must_exist=True)
        proof = getattr(context, 'artifact_identities', {}).get(key)
        if proof is None:
            proof = {**hash_identity(path, check=context.check), 'relative_path': artifact['relative_path']}
        if any(proof[field] != artifact[field] for field in ('relative_path', 'sha256', 'size_bytes')):
            raise ArtifactIdentityError('ARTIFACT_CHANGED: 产物声明与worker校验结果不一致')
        check_proof(path, proof)
        verified[key] = proof
    return verified
