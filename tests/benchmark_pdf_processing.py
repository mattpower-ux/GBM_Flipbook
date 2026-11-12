"""Local, disposable full-PDF benchmark. Never contacts or changes production."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def worker(repo, pdf, repeat):
    sys.path.insert(0,str(Path(repo).resolve()))
    import main
    import psutil
    with tempfile.TemporaryDirectory(prefix='flipbook-benchmark-') as directory:
        main.active_storage_path=Path(directory)
        count=main.get_pdf_page_count(Path(pdf))
        for run in range(repeat):
            slug=f'benchmark-{run}'
            manifest={'slug':slug,'title':'Benchmark','original_pdf_path':str(Path(pdf).resolve()),
                      'page_count':count,'pages':[],'links':[],'status':'uploaded'}
            main.write_manifest(slug,manifest)
            start=1
            while start:
                before=time.monotonic()
                result=main.process_publication_batch(slug,start,5)
                print(json.dumps({'run':run+1,'start_page':start,'seconds':round(time.monotonic()-before,3),
                    'rss':psutil.Process().memory_info().rss,'status':result['status']}),flush=True)
                start=result['next_start_page']
            assert len(list((Path(directory)/slug/'pages').glob('*.jpg')))==count
            assert len(list((Path(directory)/slug/'thumbs').glob('*.jpg')))==count
            final=main.read_manifest(slug)
            assert final['status']=='processed'
            digest=hashlib.sha256()
            for image in sorted((Path(directory)/slug).rglob('*.jpg')):
                digest.update(str(image.relative_to(Path(directory)/slug)).replace('\\','/').encode())
                digest.update(image.read_bytes())
            print(json.dumps({'run':run+1,'image_sha256':digest.hexdigest(),'links':len(final.get('links',[])),
                'toc_page_number':final.get('toc_page_number')}),flush=True)
        print(json.dumps({'complete':True,'pages':count,'runs':repeat}),flush=True)


def monitor(repo,pdf,label,repeat):
    import psutil
    target=Path('.benchmark')
    target.mkdir(exist_ok=True)
    with (target/f'{label}.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen([sys.executable,__file__,'--worker','--repo',repo,'--pdf',pdf,'--repeat',str(repeat)],stdout=log,stderr=log)
        root=psutil.Process(proc.pid)
        peak=0; samples=[]; started=time.monotonic()
        while proc.poll() is None:
            try:
                processes=[root]+root.children(recursive=True)
                rss=sum(p.memory_info().rss for p in processes if p.is_running())
                peak=max(peak,rss)
                samples.append([round(time.monotonic()-started,3),rss,len(processes)])
            except (psutil.NoSuchProcess,psutil.AccessDenied): pass
            time.sleep(.025)
        result={'label':label,'returncode':proc.returncode,'seconds':round(time.monotonic()-started,2),
                'peak_process_tree_rss_bytes':peak,'peak_process_tree_rss_mib':round(peak/1048576,2),
                'platform':sys.platform,'python':sys.version,'samples':samples}
        (target/f'{label}.json').write_text(json.dumps(result),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='samples'}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--worker',action='store_true');parser.add_argument('--repo',required=True)
    parser.add_argument('--pdf',required=True);parser.add_argument('--label',default='fixed');parser.add_argument('--repeat',type=int,default=1)
    args=parser.parse_args()
    if args.worker: worker(args.repo,args.pdf,args.repeat)
    else: monitor(args.repo,args.pdf,args.label,args.repeat)
