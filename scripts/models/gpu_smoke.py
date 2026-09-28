"""Actual GPU operators, not a cuda_available proxy; output is environment evidence."""
import json
import platform
import time
import torch
import torchvision
from torch.nn import functional as F
from torchvision.ops import nms, roi_align

torch.manual_seed(17)
torch.cuda.reset_peak_memory_stats()
checks = {}
started = time.perf_counter()
a = torch.randn(128,128,device='cuda')
checks['matmul'] = bool(torch.isfinite(a @ a).all())
x = torch.randn(1,3,64,64,device='cuda')
checks['conv2d'] = bool(torch.isfinite(F.conv2d(x,torch.randn(8,3,3,3,device='cuda'))).all())
q = torch.randn(1,4,32,64,device='cuda',dtype=torch.bfloat16)
checks['sdpa_bfloat16'] = bool(torch.isfinite(F.scaled_dot_product_attention(q,q,q)).all())
boxes = torch.tensor([[0,0,10,10],[1,1,9,9],[20,20,30,30]],device='cuda',dtype=torch.float32)
checks['torchvision_nms'] = nms(boxes,torch.tensor([.9,.8,.7],device='cuda'),.5).tolist() == [0,2]
checks['roi_align'] = bool(torch.isfinite(roi_align(x,[boxes],(3,3))).all())
torch.cuda.synchronize()
report = {'schema_version':'1.0','python':platform.python_version(),'torch':torch.__version__,
          'torchvision':torchvision.__version__,'cuda_build':torch.version.cuda,'cudnn':torch.backends.cudnn.version(),
          'device':torch.cuda.get_device_name(),'capability':torch.cuda.get_device_capability(),
          'compiled_arches':torch.cuda.get_arch_list(),'checks':checks,'elapsed_seconds':time.perf_counter()-started,
          'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'kind':'synthetic_operator_smoke_not_video_accuracy'}
print(json.dumps(report,indent=2))
if not all(checks.values()):
    raise SystemExit(1)
