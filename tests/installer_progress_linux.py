"""Regresión de la TUI con una terminal Linux real; no instala paquetes."""
import fcntl
import os
from pathlib import Path
import pty
import select
import signal
import struct
import tempfile
import time

UI = Path(__file__).resolve().parents[1]/'scripts/deploy/platform_ui.sh'


def terminal_script(folder, body, width=80, timeout=8):
    logdir=folder/('logs-'+str(time.monotonic_ns()));logdir.mkdir()
    script=folder/('case-'+str(time.monotonic_ns())+'.sh')
    script.write_text('set -euo pipefail\nsource '+str(UI)+'\nDRAPE_LOG_DIR='+str(logdir)+'\nTOTAL=1\n'+body+'\n')
    pid,master=pty.fork()
    if pid==0:
        fcntl.ioctl(1, __import__('termios').TIOCSWINSZ,struct.pack('HHHH',30,width,0,0))
        os.execve('/bin/bash',['bash',str(script)],dict(os.environ,TERM='xterm-256color'))
    output=b'';deadline=time.monotonic()+timeout;status=None
    try:
        while time.monotonic()<deadline:
            ready,_,_=select.select([master],[],[],.1)
            if ready:
                try:output+=os.read(master,65536)
                except OSError:pass
            done,value=os.waitpid(pid,os.WNOHANG)
            if done:
                status=os.waitstatus_to_exitcode(value);break
        if status is None:
            os.kill(pid,signal.SIGTERM);os.waitpid(pid,0)
            raise AssertionError('La TUI no terminó dentro del tiempo de prueba')
        return status,output.decode('utf-8',errors='replace'),logdir
    finally:
        os.close(master)


if __name__=='__main__':
    assert os.name=='posix'
    with tempfile.TemporaryDirectory(prefix='drapemind-progress-') as temp:
        folder=Path(temp)
        script='''worker() {
 [[ ! -t 0 ]] || return 9
 echo PRIVATE_MARKER
 sleep 0.4
 printf 'dlstatus:3:37.25:Downloading package 3 of 8\\n' >"$DRAPE_APT_STATUS_FILE"
 sleep 0.6
 printf 'pmstatus:acl:66.50:Configuring acl\\n' >>"$DRAPE_APT_STATUS_FILE"
 sleep 0.6
}
run_step 'APT status test' worker
'''
        for width in (42,80,120):
            status,text,logs=terminal_script(folder,script,width)
            assert status==0,(status,text)
            assert '37.25%' in text and '66.50%' in text
            assert 'PRIVATE_MARKER' not in text
            assert 'PRIVATE_MARKER' in next(logs.glob('*.log')).read_text()
            assert 'Etapas completadas: 1/1' in text
            assert '\x1b[?25h' in text
        print('PASS: APT percentages preserved at 42/80/120 columns; stdin detached; logs private')
        script='''stopped() { kill -STOP "$BASHPID"; sleep 30; }
run_step 'Suspension test' stopped
'''
        start=time.monotonic();status,text,logs=terminal_script(folder,script)
        assert status==125,(status,text)
        assert time.monotonic()-start<4
        assert 'suspendido' in text
        print('PASS: stopped worker is detected and terminated instead of looping forever')
        script='''worker() { sleep 0.5; }
run_step 'No provider metrics' worker
'''
        status,text,logs=terminal_script(folder,script)
        assert status==0 and 'porcentaje no disponible' in text
        print('PASS: no fabricated percentage when the provider has no metric')
