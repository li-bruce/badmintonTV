"""Lazy ML adapters; no framework dependency in platform/control plane."""
import hashlib
import json
import math
import os
from pathlib import Path
import time

from .protocol import ModelBlocked, InvalidRequest, atomic_write_json, make_artifact, resolve_relative
from .registry import REQUIRED_FILES
from .storage import reserve


def weights_dir(root, name):
    folder = resolve_relative(root, 'models/weights/' + name, owner='models')
    manifest = resolve_relative(root,'models/weights/'+name+'/weights-manifest.json',owner='models')
    if not manifest.is_file():
        raise ModelBlocked('MODEL_NOT_INSTALLED','缺少已校验的本地权重清单')
    try:
        files = json.loads(manifest.read_text(encoding='utf-8'))['files']
        if not isinstance(files,list) or any(not isinstance(f,dict) or not {'relative_path','sha256','size_bytes'}.issubset(f) for f in files):
            raise ValueError('invalid file entries')
        verified_names = {Path(f['relative_path']).name for f in files}
        if not REQUIRED_FILES[name].issubset(verified_names):
            raise ValueError('incomplete manifest')
    except (ValueError,TypeError,KeyError):
        raise ModelBlocked('WEIGHT_MANIFEST_INVALID','权重清单不完整或损坏') from None
    for item in files:
        path = resolve_relative(root,item['relative_path'],owner='models')
        if not path.is_file():
            raise ModelBlocked('MODEL_NOT_INSTALLED','权重文件缺失')
        if path.parent != folder or path.stat().st_size != item['size_bytes']:
            raise ModelBlocked('WEIGHT_MANIFEST_INVALID','权重路径或大小不匹配模型清单')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream,'sha256').hexdigest()
        if digest != item['sha256']:
            raise ModelBlocked('WEIGHT_HASH_MISMATCH','权重校验失败')
    return folder


def get_torch():
    try:
        import torch
    except ImportError:
        raise ModelBlocked('DEPENDENCY_NOT_INSTALLED','当前Python未安装torch；请使用模型WSL环境') from None
    except (OSError,RuntimeError):
        raise ModelBlocked('DEPENDENCY_UNAVAILABLE','torch二进制依赖加载失败；请核验隔离环境与驱动兼容') from None
    if not torch.cuda.is_available():
        raise ModelBlocked('CUDA_UNAVAILABLE','当前模型配置需要可用CUDA设备')
    torch.cuda.reset_peak_memory_stats()
    return torch


def decode_samples(path, asset, p):
    try:
        import av
    except ImportError:
        raise ModelBlocked('DEPENDENCY_NOT_INSTALLED','缺少PyAV') from None
    start, end = p.get('start_ms',0), p.get('end_ms',min(asset['duration_ms'],10000))
    fps, maximum = p.get('sample_fps',4), p.get('max_frames',60)
    if type(start) is not int or type(end) is not int or not (0 <= start < end <= asset['duration_ms']) or end-start > 30000:
        raise ValueError('source interval must be integer milliseconds, within duration, at most 30 seconds')
    if isinstance(fps,bool) or not isinstance(fps,(int,float)) or not (.5 <= fps <= 30):
        raise ValueError('sample_fps must be between 0.5 and 30')
    if type(maximum) is not int or not (1 <= maximum <= 120):
        raise ValueError('max_frames must be 1..120')
    if (end-start)*fps/1000 > maximum:
        raise ValueError('requested sampling would exceed max_frames; reduce duration or sample_fps')
    frames = []
    decoded, pixels, previous_ms = 0, 0, None
    decode_started = time.monotonic()
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        offset = stream.start_time or 0
        container.seek(int(start/1000/stream.time_base)+offset,stream=stream,backward=True)
        next_ms = start
        for frame in container.decode(stream):
            decoded += 1
            if decoded > 10000 or time.monotonic()-decode_started > 60:
                raise ValueError('decode work bound exceeded')
            if frame.pts is None:
                raise ValueError('video frame lacks source PTS')
            source_ms = round(float((frame.pts-offset)*stream.time_base)*1000)
            if source_ms < 0 or (previous_ms is not None and source_ms <= previous_ms):
                raise ValueError('non-monotonic source timestamps require explicit PTS repair')
            previous_ms = source_ms
            if source_ms >= end:
                break
            if source_ms < next_ms:
                continue
            if len(frames) >= maximum:
                break
            pixels += frame.width*frame.height
            if frame.width*frame.height > 3840*2160 or pixels > 80_000_000:
                raise ValueError('decoded image pixel budget exceeded')
            frames.append((source_ms,frame.pts,str(stream.time_base),frame.to_image()))
            next_ms = start+(math.floor((source_ms-start)*fps/1000)+1)*1000/fps
    if not frames:
        raise ValueError('no decodable frames in requested interval')
    return frames, start, end


def execute(request, root, output_path, progress):
    p = request['parameters']
    model_id = p['model_id']
    operation = request['operation']
    # These adapters validate their own parameters and own their bounded writer
    # reservation. Dispatch before taking the legacy adapter's reservation.
    if model_id == 'tracknetv3-reuse':
        from .tracknet_reuse import execute as execute_tracknet
        return execute_tracknet(request, root, output_path, progress)
    if model_id == 'qwen3-vl-embedding-2b':
        from .vl_embedding_reuse import execute as execute_vl
        return execute_vl(request, root, output_path, progress)
    if model_id == 'torchvision-continuous-pose':
        from .continuous_pose_reuse import execute as execute_pose
        return execute_pose(request, root, output_path, progress)
    if model_id == 'bst-cg-ap-reuse':
        from .bst_reuse import execute as execute_bst
        return execute_bst(request, root, output_path, progress)
    if model_id == 'yolo11n-pose-bytetrack':
        from .yolo_pose_reuse import execute as execute_yolo
        return execute_yolo(request, root, output_path, progress)
    allowed = {'query-rule-v1':'query_parse','query-endpoint-v1':'query_parse','qwen3-0.6b':'query_parse',
               'torchvision-keypointrcnn':'pose','clip-frame-mean':'video_embedding','skeleton-temporal-v1':'movement_classification'}
    if model_id not in allowed:
        raise ModelBlocked('MODEL_NOT_REGISTERED','model_id未注册')
    if operation == 'analyze' and allowed[model_id] != 'query_parse':
        operation = allowed[model_id]
    if operation != allowed[model_id]:
        raise ValueError('operation does not match registered model capability')
    if model_id == 'skeleton-temporal-v1':
        raise ModelBlocked('TRAINING_DATA_REQUIRED','细动作真值和独立比赛测试集不足；未训练骨骼分类器')
    producer = {'module':'models','model_id':model_id,'version':'0.1.0','job_id':request['job_id'],'attempt_id':request['attempt_id']}
    with reserve(root, 100_000_000):
        output_path.mkdir(parents=True,exist_ok=True)
        if operation == 'query_parse':
            from .query import QueryParseError
            try:
                return run_query(request,root,output_path,progress,producer)
            except QueryParseError as exc:
                if exc.code.startswith('endpoint_') or exc.code in {'remote_endpoint_disabled','invalid_endpoint_config'}:
                    raise ModelBlocked(exc.code,str(exc)) from None
                raise InvalidRequest(str(exc),exc.code) from None
        if len(request['assets']) != 1:
            raise ValueError('first baseline accepts exactly one asset per job')
        asset = request['assets'][0]
        path = resolve_relative(root,asset['relative_path'])
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest() != asset['sha256']:
                raise ValueError('source asset SHA256 mismatch')
        started = time.perf_counter()
        progress('decode',message='Decode bounded source window')
        frames,start,end = decode_samples(path,asset,p)
        torch = get_torch()
        progress('load_model',message='Load verified local weights')
        try:
            if operation == 'pose':
                payload = run_pose(root,frames,p,torch,progress)
                kind = 'pose_features'
            else:
                payload = run_clip(root,frames,p,torch,progress)
                kind = 'video_embedding'
        except ImportError:
            raise ModelBlocked('DEPENDENCY_NOT_INSTALLED','模型环境缺少依赖') from None
        torch.cuda.synchronize()
        payload.update(schema_version='1.0',asset_id=asset['asset_id'],match_id=asset['match_id'],
                       start_ms=start,end_ms=end,source_sha256=asset['sha256'],producer=producer)
        target = output_path / 'features.json'
        atomic_write_json(target,payload)
        elapsed = time.perf_counter()-started
        report = {'schema_version':'1.0','model_id':model_id,'asset_id':asset['asset_id'],
                  'sampled_frames':len(frames),'source_window_ms':end-start,'elapsed_seconds':elapsed,
                  'seconds_per_video_hour_extrapolated':elapsed/((end-start)/1000)*3600,
                  'speed_caveat':'single short clip including load/decode; not full-match throughput',
                  'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved(),
                  'device':torch.cuda.get_device_name(),'torch':torch.__version__,'cuda_build':torch.version.cuda,
                  'source_type':asset['source_type'],'camera_type':asset['camera_type'],'discipline':asset['discipline'],
                  'accuracy':None,'recall':None,'manual_review_required':True,
                  'unsupported':['fine_hand_technique','player_identity','contact_time','temporal_action_classification']}
        report_path = output_path / 'report.json'
        atomic_write_json(report_path,report)
        return {'artifacts':[make_artifact(root,target,kind,producer),make_artifact(root,report_path,'evaluation_report',producer)],'events':[]}


def run_query(request,root,output_path,progress,producer):
    from .query import parse_rule, parse_endpoint, validate_query
    p = request['parameters']
    text = p.get('text')
    if not isinstance(text,str) or not (1 <= len(text) <= 2000):
        raise ValueError('query text required, max 2000 characters')
    kwargs = {'query_id':p.get('query_id',request['job_id']), 'player_id':p.get('player_id'), 'scope':p.get('scope')}
    progress('query_parse',message='Parse query without video upload')
    started = time.perf_counter()
    if p['model_id'] == 'query-rule-v1':
        spec,warnings = parse_rule(text,**kwargs)
    elif p['model_id'] == 'query-endpoint-v1':
        config_path = os.environ.get('BTV_LLM_CONFIG')
        if not config_path or not Path(config_path).is_file():
            raise ModelBlocked('ENDPOINT_NOT_CONFIGURED','未设置管理员端点配置')
        config = json.loads(Path(config_path).read_text(encoding='utf-8'))
        spec,warnings = parse_endpoint(text,config,**kwargs)
    else:
        spec,warnings = run_qwen(text,root,kwargs,progress)
    validate_query(spec)
    target = output_path / 'query.json'
    atomic_write_json(target,spec)
    report_path = output_path / 'query-report.json'
    atomic_write_json(report_path,{'schema_version':'1.0','model_id':p['model_id'],'elapsed_seconds':time.perf_counter()-started,
                                  'warnings':warnings,'is_video_evidence':False,'human_review_required':True})
    return {'artifacts':[make_artifact(root,target,'query_spec',producer),make_artifact(root,report_path,'query_parse_report',producer)],'events':[]}


def run_qwen(text,root,kwargs,progress):
    from .query import parse_rule, validate_query, validate_semantics, QUERY_SYSTEM_PROMPT
    reference,warnings = parse_rule(text,**kwargs)
    folder = weights_dir(root,'qwen3-0.6b')
    torch = get_torch()
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        raise ModelBlocked('DEPENDENCY_NOT_INSTALLED','缺少transformers') from None
    tokenizer = AutoTokenizer.from_pretrained(str(folder),local_files_only=True,trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(str(folder),local_files_only=True,trust_remote_code=False,
                                             torch_dtype=torch.bfloat16).to('cuda').eval()
    messages = [{'role':'system','content':QUERY_SYSTEM_PROMPT}, {'role':'user','content':text}]
    prompt = tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
    inputs = tokenizer(prompt,return_tensors='pt').to('cuda')
    with torch.inference_mode():
        generated = model.generate(**inputs,max_new_tokens=768,do_sample=False)
    raw = tokenizer.decode(generated[0,inputs['input_ids'].shape[1]:],skip_special_tokens=True).strip()
    try:
        spec = json.loads(raw)
        validate_query(spec)
        spec = validate_semantics(spec,reference)
    except (ValueError,TypeError,KeyError):
        raise ModelBlocked('LLM_SCHEMA_OR_SEMANTIC_FAILURE','小模型输出未通过schema/条件保真校验；没有自动降级替代') from None
    spec.update(query_id=reference['query_id'],text=text,player_id=reference['player_id'],scope=reference['scope'])
    warnings.append('experimental local Qwen; schema validity is not video accuracy')
    progress('query_parse',current=1,total=1,unit='query',message='Validated local model output')
    return spec,warnings


def run_pose(root,frames,p,torch,progress):
    from torchvision.models.detection import keypointrcnn_resnet50_fpn
    from torchvision.transforms.functional import pil_to_tensor
    folder = weights_dir(root,'torchvision-pose')
    model = keypointrcnn_resnet50_fpn(weights=None,weights_backbone=None,min_size=480,max_size=854)
    state = torch.load(folder/'keypointrcnn_resnet50_fpn_coco-fc266e95.pth',map_location='cpu',weights_only=True)
    model.load_state_dict(state)
    model.to('cuda').eval()
    threshold = p.get('score_threshold',.7)
    if type(threshold) not in (int,float) or not .1 <= threshold <= .99:
        raise ValueError('score_threshold must be 0.1..0.99')
    output = []
    with torch.inference_mode():
        for index,(source_ms,pts,base,pil) in enumerate(frames):
            prediction = model([pil_to_tensor(pil).to(device='cuda',dtype=torch.float32)/255])[0]
            keep = (prediction['scores'] >= threshold).nonzero().flatten()[:10]
            detections = [{'detection_id':f'{index}:{int(i)}','track_id':None,'player_id':None,
                           'box_xyxy':prediction['boxes'][i].cpu().tolist(),'score':float(prediction['scores'][i]),
                           'keypoints_xyv':prediction['keypoints'][i].cpu().tolist(),
                           'keypoint_scores':prediction['keypoints_scores'][i].cpu().tolist()} for i in keep]
            output.append({'source_ms':source_ms,'pts':pts,'time_base':base,'width':pil.width,'height':pil.height,'detections':detections})
            progress('pose',current=index+1,total=len(frames),unit='frame',message='COCO17 preannotation; identities unknown')
    return {'format':'coco17-source-pixels','frames':output,'tracking':'not_implemented',
            'warning':'COCO visibility v is not calibrated badminton keypoint certainty; raw scores retained; no fine-action events'}


def run_clip(root,frames,p,torch,progress):
    from transformers import CLIPModel, CLIPProcessor
    folder = weights_dir(root,'clip-vit-base-patch32')
    model = CLIPModel.from_pretrained(str(folder),local_files_only=True,use_safetensors=False).to('cuda').eval()
    processor = CLIPProcessor.from_pretrained(str(folder),local_files_only=True)
    vectors = []
    texts = p.get('texts',['a badminton player hitting a net shot','a badminton player smashing',
                         'a badminton player moving backwards','a badminton player serving'])
    if not isinstance(texts,list) or not 1 <= len(texts) <= 16 or any(not isinstance(t,str) or not 1 <= len(t) <= 200 for t in texts):
        raise ValueError('texts must contain 1..16 prompts, at most 200 characters each')
    with torch.inference_mode():
        for index,(_,_,_,pil) in enumerate(frames):
            inputs = processor(images=pil,return_tensors='pt').to('cuda')
            vector = model.get_image_features(**inputs)
            vectors.append(vector / vector.norm(dim=-1,keepdim=True))
            progress('video_embedding',current=index+1,total=len(frames),unit='frame',message='Frame CLIP feature')
        mean = torch.cat(vectors).mean(dim=0)
        mean /= mean.norm()
        text_inputs = processor(text=texts,return_tensors='pt',padding=True,truncation=True).to('cuda')
        text_features = model.get_text_features(**text_inputs)
        text_features /= text_features.norm(dim=-1,keepdim=True)
        similarities = (text_features @ mean).cpu().tolist()
    return {'format':'clip-frame-mean-512','embedding':mean.cpu().tolist(),
            'sample_times_ms':[f[0] for f in frames],
            'text_similarity':[{'text':text,'cosine_similarity':score,'is_probability':False} for text,score in zip(texts,similarities)],
            'warning':'Frame average has no temporal order and does not establish fine badminton techniques; multilingual retrieval unvalidated'}
