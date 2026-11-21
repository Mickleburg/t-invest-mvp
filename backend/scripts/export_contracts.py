"""Rebuild the frozen contract; implemented operations come from the real app."""
import json
from pathlib import Path
import yaml
from backend.app.main import create_app

ROOT=Path(__file__).resolve().parents[2]

def document():
    spec=create_app().openapi()
    spec['info']={'title':'TradeGuard MVP','version':'0.1.0','description':'Implemented prototype subset + proposed CP2/CP3 operations. x-implementation-status is normative; planned paths are not served.'}
    spec['x-contract-state']='provisional-team-review-required'
    for item in spec['paths'].values():
        for operation in item.values():operation['x-implementation-status']='implemented'
    plan=json.loads((ROOT/'contracts/trade_plan.schema.json').read_text(encoding='utf-8'))
    def refs(value):
        if isinstance(value,dict):return {k:(v.replace('#/$defs/','#/components/schemas/Plan_') if k=='$ref' else refs(v)) for k,v in value.items()}
        if isinstance(value,list):return [refs(v) for v in value]
        return value
    schemas=spec['components']['schemas']
    schemas['TradePlan']=refs({k:v for k,v in plan.items() if k not in ('$schema','$id','$defs')})
    for name,value in plan['$defs'].items():schemas['Plan_'+name]=refs(value)
    schemas['PlanChanges']={'type':'object','additionalProperties':False,'minProperties':1,
      'properties':{k:v for k,v in schemas['TradePlan']['properties'].items() if k not in ('id','version','status','confirmation')}}
    schemas['PlanPatch']={'type':'object','additionalProperties':False,'required':['expected_version','changes'],
      'properties':{'expected_version':{'type':'integer','minimum':1},'changes':{'$ref':'#/components/schemas/PlanChanges'}}}
    schemas['PlanConfirmation']={'type':'object','additionalProperties':False,'required':['version','content_hash','request_id'],
      'properties':{'version':{'type':'integer','minimum':1},'content_hash':{'type':'string','pattern':'^[a-f0-9]{64}$'},'request_id':{'type':'string','format':'uuid'}}}
    schemas['MonitoringState']={'type':'object','additionalProperties':False,'required':['plan_id','confirmed_version','state','last_checked_at','next_check_at'],
      'properties':{'plan_id':{'type':'string','format':'uuid'},'confirmed_version':{'type':'integer','minimum':1},'state':{'enum':['not_started','active','paused','error']},
      'last_checked_at':{'type':['string','null'],'format':'date-time'},'next_check_at':{'type':['string','null'],'format':'date-time'}}}
    schemas['Check']={'type':'object','additionalProperties':False,'required':['id','plan_id','plan_version','rule_id','checked_at','status','source_ids','observed_value'],
      'properties':{'id':{'type':'string'},'plan_id':{'type':'string'},'plan_version':{'type':'integer'},'rule_id':{'type':'string'},'checked_at':{'type':'string','format':'date-time'},
      'status':{'enum':['satisfied','affected','insufficient_data','error']},'source_ids':{'type':'array','items':{'type':'string'}},'observed_value':{'type':['string','null']}}}
    schemas['Notification']={'type':'object','additionalProperties':False,'required':['id','plan_id','plan_version','check_id','created_at','text','delivery_status'],
      'properties':{'id':{'type':'string'},'plan_id':{'type':'string'},'plan_version':{'type':'integer'},'check_id':{'type':'string'},'created_at':{'type':'string','format':'date-time'},
      'text':{'type':'string'},'delivery_status':{'enum':['stored','delivered','failed']}}}
    params=[{'name':'plan_id','in':'path','required':True,'schema':{'type':'string','format':'uuid'}}]
    def planned(path,method,name,response_schema,request=None,parameters=None):
        op={'operationId':name,'summary':name,'description':'PLANNED, not implemented. Calling this route today returns 404; responses below are the target contract.',
          'x-implementation-status':'planned','parameters':parameters or [],'responses':{'200':{'description':'Target success','content':{'application/json':{'schema':response_schema}}}}}
        for code in ('404','409','422','503'):op['responses'][code]={'description':{'404':'Not found','409':'Stale version/hash, already confirmed or idempotency conflict','422':'Incomplete/invalid plan or request','503':'Source/provider unavailable'}[code],
            'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Error'}}}}
        if request:op['requestBody']={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/'+request}}}}
        spec['paths'].setdefault(path,{})[method]=op
    planned('/api/sessions/{sid}/messages','get','message_history',{'type':'array','items':{'$ref':'#/components/schemas/MessageRecord'}},parameters=[{'name':'sid','in':'path','required':True,'schema':{'type':'string'}}])
    planned('/api/sessions/{sid}/plan','get','session_draft',{'$ref':'#/components/schemas/TradePlan'},parameters=[{'name':'sid','in':'path','required':True,'schema':{'type':'string'}}])
    for method,name,request in [('get','get_plan',None),('patch','update_draft','PlanPatch')]:planned('/api/plans/{plan_id}',method,name,{'$ref':'#/components/schemas/TradePlan'},request,params)
    planned('/api/plans/{plan_id}/confirm','post','confirm_version',{'$ref':'#/components/schemas/TradePlan'},'PlanConfirmation',params)
    planned('/api/plans/{plan_id}/monitoring','get','monitoring_state',{'$ref':'#/components/schemas/MonitoringState'},parameters=params)
    for suffix,model in [('notifications','Notification'),('checks','Check')]:planned('/api/plans/{plan_id}/'+suffix,'get',suffix,{'type':'array','items':{'$ref':'#/components/schemas/'+model}},parameters=params)
    return spec

if __name__=='__main__':
    (ROOT/'contracts/openapi.yaml').write_text(yaml.safe_dump(document(),allow_unicode=True,sort_keys=False),encoding='utf-8')
