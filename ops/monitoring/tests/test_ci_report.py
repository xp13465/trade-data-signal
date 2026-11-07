from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import report_ci_tests as report

def test_failure_counts_and_ids(tmp_path,capsys):
    p=tmp_path/'result.xml'
    p.write_text('<testsuites><testsuite><testcase classname="module" name="ok"/><testcase classname="module" name="bad"><failure>private traceback omitted</failure></testcase><testcase name="error"><error/></testcase><testcase name="skip"><skipped/></testcase></testsuite></testsuites>')
    assert report.read_report(p)=={'tests':4,'failures':1,'errors':1,'skipped':1,'failed_ids':['module::bad','::error'],'omitted_failure_ids':0}
    assert report.main([str(p)])==0
    output=capsys.readouterr().out
    assert 'module::bad' in output and 'private traceback' not in output

@pytest.mark.parametrize('raw',['<bad','<testsuites/>',''])
def test_bad_or_empty_report_fails_closed(tmp_path,raw,capsys):
    p=tmp_path/'bad.xml';p.write_text(raw)
    assert report.main([str(p)])==2
    assert '不能视为通过' in capsys.readouterr().out

def test_annotation_escaping_and_secret_filter():
    assert report.escape('x%\n::error\ry')=='x%25%0A::error%0Dy'
    assert 'ghp_' not in report.safe_id('case[ghp_1234567890abcdef]')
    assert '/home/' not in report.safe_id('case[/home/runner/private]')
