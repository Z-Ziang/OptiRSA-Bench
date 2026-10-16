"""Windows DPAPI secret storage; credential never appears in configuration/logs."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(raw,protect):
    if os.name!='nt':raise RuntimeError('DPAPI storage requires Windows')
    buf=ctypes.create_string_buffer(raw);source=Blob(len(raw),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)));out=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    fn=crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fn.restype=wintypes.BOOL
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(out)):raise ctypes.WinError(ctypes.get_last_error())
    try:return ctypes.string_at(out.data,out.size)
    finally:kernel.LocalFree(ctypes.cast(out.data,ctypes.c_void_p))


def store(path,secret):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(_crypt(secret.encode(),True))


def load(path):return _crypt(Path(path).read_bytes(),False).decode()


if __name__=='__main__':
    import argparse,sys
    p=argparse.ArgumentParser();p.add_argument('--store',required=True);a=p.parse_args()
    secret=sys.stdin.read().strip()
    if not secret:raise SystemExit('No credential supplied')
    store(a.store,secret)
    print('Credential stored with Windows user-bound DPAPI encryption.')
