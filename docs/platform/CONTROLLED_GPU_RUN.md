# 可信离线 GPU 任务入口

本轮使用同一原生 `D:/video/platform/runtime.sqlite3`。不另建账本、不绕过job/attempt租约、不开放shell API。运行前由models明确让出窗口，确认没有旧queued/running任务、没有常驻worker竞争领取，GPU没有active/orphaned租约。

管理员在实际集成/渲染checkout运行Windows平台Python，设置 `BTV_RENDER_BACKEND=cpu|nvenc|auto`（默认cpu）与精确 `BTV_RENDER_COMMAND_JSON=["D:/video/runtime/platform/env/Scripts/python.exe","-m","packages.render"]`。`PYTHONPATH`/cwd指当前checkout，不把旧工作树长期固定在产品里。auto也必须先获得GPU窗口，再由render判断是否有带原因的CPU回退。

以下为可信本地脚本示例；request须先通过JobRequest合同验证，来自本轮已核验的普通素材，不能使用训练专用素材制作集锦。grant必须在models协调之后，窗口和任务标识每次唯一：

```python
import json, os, uuid
from pathlib import Path
from packages.contracts import JobRequest
from packages.runtime import Queue
from packages.runtime.gpu import GPUCoordinator
from packages.runtime.worker import run_once

request = JobRequest.model_validate_json(Path('request.json').read_text()).model_dump(mode='json')
assert request['operation'] == 'render'
q = Queue('D:/video/platform/runtime.sqlite3')
with q.connection() as db:
    assert db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] == 0
gpu = GPUCoordinator(q.db_path)
assert gpu.status()['lease'] is None
backend = os.environ.get('BTV_RENDER_BACKEND', 'cpu')
assert backend in ('nvenc', 'auto')
window = 'render-bench-' + uuid.uuid4().hex
gpu.grant_window(window, ['render-nvenc'], 600,
    coordination_note='models已明确让出本次10分钟窗口')
job = q.enqueue('render', {'model_id':'render-nvenc', 'gpu_required':True,
    'render_backend':backend, 'assets':request['assets'], 'parameters':request['parameters']})
result = run_once(q, 'D:/video', worker_id=window)
assert result['job_id'] == job['job_id']
assert gpu.status()['lease'] is None  # orphaned不能强制归还
gpu.revoke_window(window, reason='已确认该任务计算停止并返还models排期')
print(json.dumps(result, ensure_ascii=False))
```

worker根据可信进程环境BTV_RENDER_BACKEND=nvenc/auto强制GPU要求并核验持久payload.model_id=render-nvenc；客户端gpu_required=false无法绕过。执行时注入`BTV_RUNTIME_DB`（当前queue.db_path）、`BTV_GPU_LEASE_ID`（本次claim返回值）、`BTV_RENDER_BACKEND`；清除继承的陈旧lease ID。render可只读核对lease/window有效性、resource/model_id、job_id和attempt；请求attempt_id固定`attempt-<整数>`。渲染参数JSON不能授予租约或选择可信后端。管理员后端改变后旧配置快照显式blocked/RENDER_CONFIG_CHANGED，需新建任务。

模型沿用同法：operation=model，固定管理员model_id/model_version/adapter_operation、assets和parameters；按model_id在BTV_MODEL_COMMANDS_JSON登记WSL bridge，只运行packages.models既有协议。GPU窗口allowlist换为实际模型ID；桥接自身强制GPU租约。此示例不创设新GPU排期，也不代表实际硬件运行已通过。

验证：`pytest tests/platform/test_render_gpu_registration.py tests/platform/test_runtime.py -q` → 45 passed/1既有symlink skip，全为CPU/协议测试，未使用GPU。
