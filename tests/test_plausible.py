import sqlite3
import pytest
import plausible_stats as stats

def test_exact_query_and_results_deduplicate_without_losing_dimensions():
    conn=sqlite3.connect(':memory:')
    body=stats.query_body({'site_id':'my.site','metrics':['visitors','total_revenue'],'dimensions':['event:goal'],'date_range':['2026-01-01','2026-01-31']})
    response={'results':[{'dimensions':['Purchase'],'metrics':[8,{'value':24.5,'currency':'EUR'}]}],'meta':{'metric_warning':None}}
    a=stats.capture(conn,'website',body,response,'https://stats.example')
    b=stats.capture(conn,'website',body,response,'https://stats.example')
    assert a['added'] and not b['added'] and a['id']==b['id']
    assert stats.list_snapshots(conn)['snapshots'][0]['response']==response
    assert 'token' not in str(stats.list_snapshots(conn))

def test_invalid_response_is_not_stored():
    conn=sqlite3.connect(':memory:')
    body=stats.query_body({'site_id':'my.site'})
    with pytest.raises(ValueError,match='columns'):
        stats.capture(conn,'web',body,{'results':[{'metrics':[1],'dimensions':[]}]},'https://stats.example')
    with pytest.raises(ValueError):
        stats.query_body({'site_id':'https://site','date_range':'forever'})

def test_credentials_are_not_sent_before_configuration_validation(monkeypatch):
    monkeypatch.setenv('PLAUSIBLE_URL','http://remote.example')
    monkeypatch.setenv('PLAUSIBLE_API_KEY','sensitive')
    with pytest.raises(ValueError,match='HTTPS'):
        stats.fetch(stats.query_body({'site_id':'my.site'}))

def test_filters_ordering_and_pagination_are_preserved():
    filters=[['or',[['is','visit:country',['ES']],['contains','event:page',['/docs'],{'case_sensitive':False}]]]]
    query=stats.query_body({'site_id':'my.site','filters':filters,'page_size':10,'offset':20,'order_by':[['visitors','desc']]})
    assert query['filters']==filters and query['pagination']=={'limit':10,'offset':20}
    for bad in [[['is','time:day',['today']]],[['call','event:page',['anything']]]]:
        with pytest.raises(ValueError):stats.query_body({'site_id':'my.site','filters':bad})
