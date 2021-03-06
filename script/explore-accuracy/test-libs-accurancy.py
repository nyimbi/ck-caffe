#! /usr/bin/python
import ck.kernel as ck
import copy
import re
import argparse

# Batch size iteration parameters.
bs={
  'start':2,
  'stop':2,
  'step':2,
  'default':2
}
# Number of statistical repetitions.
num_repetitions=3
platform_tags='platform-name'
def do(i, arg):
    # Detect basic platform info.
    ii={'action':'detect',
        'module_uoa':'platform',
        'out':'out'}
    r=ck.access(ii)
    if r['return']>0: return r

    # Host and target OS params.
    hos=r['host_os_uoa']
    hosd=r['host_os_dict']

    tos=r['os_uoa']
    tosd=r['os_dict']
    tdid=r['device_id']
    # Program and command.
    program='caffe'
    cmd_key='test_gpu'

    # Load Caffe program meta and desc to check deps.
    ii={'action':'load',
        'module_uoa':'program',
        'data_uoa':program}
    rx=ck.access(ii)
    if rx['return']>0: return rx
    mm=rx['dict']

    # Get compile-time and run-time deps.
    cdeps=mm.get('compile_deps',{})
    rdeps=mm.get('run_deps',{})
    # Merge rdeps with cdeps for setting up the pipeline (which uses
    # common deps), but tag them as "for_run_time".
    for k in rdeps:
        cdeps[k]=rdeps[k]
        cdeps[k]['for_run_time']='yes'
    # Caffe libs.
    depl=copy.deepcopy(cdeps['lib-caffe'])
    if (arg.tos is not None) and (arg.did is not None):
        tos=arg.tos
        tdid=arg.did

    ii={'action':'resolve',
        'module_uoa':'env',
        'host_os':hos,
        'target_os':tos,
        'device_id':tdid,
        'out':'con',
        'deps':{'lib-caffe':copy.deepcopy(depl)}
    }
    r=ck.access(ii)
    if r['return']>0: return r

    udepl=r['deps']['lib-caffe'].get('choices',[]) # All UOAs of env for Caffe libs.
    if len(udepl)==0:
        return {'return':1, 'error':'no installed Caffe libs'}

    # Caffe models.
    depm=copy.deepcopy(cdeps['caffemodel'])

    ii={'action':'resolve',
        'module_uoa':'env',
        'host_os':hos,
        'target_os':tos,
        'device_id':tdid,
        'out':'con',
        'deps':{'caffemodel':copy.deepcopy(depm)}
    }
    r=ck.access(ii)
    if r['return']>0: return r

    udepm=r['deps']['caffemodel'].get('choices',[]) # All UOAs of env for Caffe models.
    if len(udepm)==0:
        return {'return':1, 'error':'no installed Caffe models'}

    # Prepare pipeline.
    cdeps['lib-caffe']['uoa']=udepl[0]
    cdeps['caffemodel']['uoa']=udepm[0]

    ii={'action':'pipeline',
        'prepare':'yes',
        'dependencies':cdeps,

        'module_uoa':'program',
        'data_uoa':program,
        'cmd_key':cmd_key,

        'target_os':tos,
        'device_id':tdid,

        'no_state_check':'yes',
        'no_compiler_description':'yes',
        'skip_calibration':'yes',

        'env':{
          'CK_CAFFE_SKIP_BACKWARD':1,
          'OPENBLAS_NUM_THREADS':4
        },

        'cpu_freq':'max',
        'gpu_freq':'max',

        'flags':'-O3',
        'speed':'no',
        'energy':'no',

        'skip_print_timers':'yes',
        'out':'con'
    }

    r=ck.access(ii)
    if r['return']>0: return r

    fail=r.get('fail','')
    if fail=='yes':
        return {'return':10, 'error':'pipeline failed ('+r.get('fail_reason','')+')'}

    ready=r.get('ready','')
    if ready!='yes':
        return {'return':11, 'error':'pipeline not ready'}

    state=r['state']
    tmp_dir=state['tmp_dir']

    # Remember resolved deps for this benchmarking session.
    xcdeps=r.get('dependencies',{})

    # Clean pipeline.
    if 'ready' in r: del(r['ready'])
    if 'fail' in r: del(r['fail'])
    if 'return' in r: del(r['return'])

    pipeline=copy.deepcopy(r)

    # For each Caffe lib.*******************************************************
    for lib_uoa in udepl:
        # Load Caffe lib.
        ii={'action':'load',
            'module_uoa':'env',
            'data_uoa':lib_uoa}
        r=ck.access(ii)
        if r['return']>0: return r
        # Get the tags from e.g. 'BVLC Caffe framework (libdnn,viennacl)'
        lib_name=r['data_name']
        lib_tags=re.match('BVLC Caffe framework \((?P<tags>.*)\)', lib_name)
        lib_tags=lib_tags.group('tags').replace(' ', '').replace(',', '-')
        # Skip some libs with "in [..]" or "not in [..]".

#        if lib_tags in ['opencl-clblast-tune']: continue

        if lib_tags not in ['opencl-libdnn-clblast-tune']: continue

#        if lib_tags not in ['opencl-clblast-tune', 'opencl-clblast']: continue
#        if lib_tags not in ['opencl-libdnn-clblast-tune', 'opencl-libdnn-clblast']: continue
#        if lib_tags not in ['opencl-libdnn-viennacl', 'opencl-viennacl']: continue
        
        skip_compile='no'

        cmd_key='time_gpu_fp16'

        # For each Caffe model.*************************************************
        for model_uoa in udepm:
            # Load Caffe model.
            ii={'action':'load',
                'module_uoa':'env',
                'data_uoa':model_uoa}
            r=ck.access(ii)
            if r['return']>0: return r
            # Get the tags from e.g. 'Caffe model (net and weights) (deepscale, squeezenet, 1.1)'
            model_name=r['data_name']
            model_tags = re.match('Caffe model \(net and weights\) \((?P<tags>.*)\)', model_name)
            model_tags = model_tags.group('tags').replace(' ', '').replace(',', '-')
            # Skip some models with "in [..]" or "not in [..]".
            if model_tags in []: continue

            record_repo='local'
            record_uoa=model_tags+'-'+lib_tags

            # Prepare pipeline.
            ck.out('---------------------------------------------------------------------------------------')
            ck.out('%s - %s' % (lib_name, lib_uoa))
            ck.out('%s - %s' % (model_name, model_uoa))
            ck.out('Experiment - %s:%s' % (record_repo, record_uoa))

            # Prepare autotuning input.
            cpipeline=copy.deepcopy(pipeline)

            # Reset deps and change UOA.
            new_deps={'lib-caffe':copy.deepcopy(depl),
                      'caffemodel':copy.deepcopy(depm)}

            new_deps['lib-caffe']['uoa']=lib_uoa
            new_deps['caffemodel']['uoa']=model_uoa

            jj={'action':'resolve',
                'module_uoa':'env',
                'host_os':hos,
                'target_os':tos,
                'device_id':tdid,
                'deps':new_deps}
            r=ck.access(jj)
            if r['return']>0: return r

            cpipeline['dependencies'].update(new_deps)

            cpipeline['no_clean']=skip_compile
            cpipeline['no_compile']=skip_compile

            cpipeline['cmd_key']=cmd_key

            ii={'action':'autotune',

                'module_uoa':'pipeline',
                'data_uoa':'program',

                'choices_order':[
                    [
                        '##choices#env#CK_CAFFE_BATCH_SIZE'
                    ]
                ],
                'choices_selection':[
                    {'type':'loop', 'start':bs['start'], 'stop':bs['stop'], 'step':bs['step'], 'default':bs['default']}
                ],

                'features_keys_to_process':['##choices#*'],

                'iterations':-1,
                'repetitions':num_repetitions,

                'record':'yes',
                'record_failed':'yes',
                'record_params':{
                    'search_point_by_features':'yes'
                },
                'record_repo':record_repo,
                'record_uoa':record_uoa,

                'tags':[ 'explore-batch-size-libs-models', cmd_key, model_tags, lib_tags, platform_tags ],

                'pipeline':cpipeline,
                'out':'con'}

            r=ck.access(ii)
            if r['return']>0: return r

            fail=r.get('fail','')
            if fail=='yes':
                return {'return':10, 'error':'pipeline failed ('+r.get('fail_reason','')+')'}

            skip_compile='yes'

    return {'return':0}

parser = argparse.ArgumentParser(description='Pipeline')
parser.add_argument("--target_os", action="store", dest="tos")
parser.add_argument("--device_id", action="store", dest="did")
myarg=parser.parse_args()


r=do({}, myarg)
if r['return']>0: ck.err(r)
