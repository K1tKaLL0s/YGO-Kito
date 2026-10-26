"""Workspace byte admission and physically reserved, bounded NEW-file sinks.

No installation, training, old-data deletion or global filesystem quota occurs
here. Only writers using this sink are bounded. Existing SQLite/installer/log
writers require their own integration; finishing the training volume is unknown.
"""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import stat

from .agent_registry import identifier
from .build_contracts import digest
from .validation import ContractError, canonical_json, fields, integer, read_json

LIMIT_BYTES=30_000_000_000


class StorageEnvelopeExceeded(ContractError):
    """Refuse the next controlled operation; never assert training can finish."""


def _hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def workspace_usage(workspace):
    """Count conservative bytes once per inode, including directory metadata.

    Symlink objects are counted, never followed. Their outside targets are not
    included: outside_bytes must explicitly account for external environment.
    """
    root=Path(workspace).resolve(strict=True)
    seen={};files=directories=symlinks=0
    def fail(error):raise error
    for directory,dirs,names in os.walk(root,followlinks=False,onerror=fail):
        for path in [Path(directory)]+[Path(directory)/name for name in names]+[Path(directory)/name for name in dirs if (Path(directory)/name).is_symlink()]:
            s=path.lstat()
            if not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode) or stat.S_ISLNK(s.st_mode)):
                raise ContractError('workspace contains unsupported storage objects')
            key=(s.st_dev,s.st_ino)
            seen[key]=max(seen.get(key,0),s.st_size,getattr(s,'st_blocks',0)*512)
            if stat.S_ISLNK(s.st_mode):symlinks+=1
            elif stat.S_ISDIR(s.st_mode):directories+=1
            else:files+=1
    return {'accounted_bytes':sum(seen.values()),'file_paths':files,'directory_paths':directories,
        'symlink_objects_not_followed':symlinks,'inode_count':len(seen),
        'outside_targets_accounted':False,'method':'sum_unique_inode_max_logical_or_allocated_bytes'}


class StorageEnvelope:
    def __init__(self,workspace,*,state_roots=(),temporary_roots=(),limit_bytes=LIMIT_BYTES,
                 outside_bytes=None,min_free_bytes=64*1024*1024,safety_margin_bytes=64*1024):
        self.workspace=Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():raise ContractError('selected workspace directory required')
        root_stat=self.workspace.stat();self._workspace_identity=(str(self.workspace),root_stat.st_dev,root_stat.st_ino)
        integer(limit_bytes,'strict storage threshold',1,LIMIT_BYTES)
        if outside_bytes is not None:integer(outside_bytes,'explicit external environment bytes',0)
        integer(min_free_bytes,'minimum physical free bytes',0)
        integer(safety_margin_bytes,'storage metadata/safety margin bytes',0)
        self.control=self.workspace/'.cache/storage-envelope-v1'
        self.limit_bytes,self.outside_bytes=limit_bytes,outside_bytes
        self.min_free_bytes,self.safety_margin_bytes=min_free_bytes,safety_margin_bytes
        self.state_roots=self._roots(state_roots);self.temporary_roots=self._roots(temporary_roots)
        self.binding={'schema_version':1,'kind':'workspace-bounded-new-file-storage-v1',
            'state_roots':[p.relative_to(self.workspace).as_posix() for p in self.state_roots],
            'temporary_roots':[p.relative_to(self.workspace).as_posix() for p in self.temporary_roots],
            'limit_bytes':limit_bytes,'outside_bytes':outside_bytes,'min_free_bytes':min_free_bytes,
            'safety_margin_bytes':safety_margin_bytes}
        self._binding_sha=digest(self.binding)

    def _inside(self,value):
        if not isinstance(value,(str,Path)) or not str(value):raise ContractError('explicit workspace path required')
        raw=Path(value);raw=raw if raw.is_absolute() else self.workspace/raw
        path=raw.absolute()
        if not path.is_relative_to(self.workspace):raise ContractError('controlled path escapes workspace')
        for p in [path,*path.parents]:
            if p==self.workspace.parent:break
            if p.is_symlink():raise ContractError('controlled storage paths cannot use symlinks')
        resolved=path.resolve()
        if not resolved.is_relative_to(self.workspace):raise ContractError('controlled path escapes workspace')
        return resolved

    def _roots(self,values):
        if not isinstance(values,(list,tuple)):raise ContractError('explicit state/temp root sequence required')
        roots=tuple(self._inside(v) for v in values)
        if len(set(roots))!=len(roots) or self.workspace in roots:raise ContractError('distinct dedicated controlled roots required')
        return roots

    def _check(self):
        root_stat=self.workspace.stat()
        current={'schema_version':1,'kind':'workspace-bounded-new-file-storage-v1',
            'state_roots':[p.relative_to(self.workspace).as_posix() for p in self.state_roots],
            'temporary_roots':[p.relative_to(self.workspace).as_posix() for p in self.temporary_roots],
            'limit_bytes':self.limit_bytes,'outside_bytes':self.outside_bytes,'min_free_bytes':self.min_free_bytes,
            'safety_margin_bytes':self.safety_margin_bytes}
        if (digest(self.binding)!=self._binding_sha or digest(current)!=self._binding_sha or
                (str(self.workspace),root_stat.st_dev,root_stat.st_ino)!=self._workspace_identity or
                self.control!=self.workspace/'.cache/storage-envelope-v1'):
            raise ContractError('storage envelope binding changed')
        for p in (*self.state_roots,*self.temporary_roots,self.control):self._inside(p)

    def audit(self,additional_bytes=0):
        self._check();integer(additional_bytes,'additional reserved bytes',0)
        usage=workspace_usage(self.workspace)
        total=None if self.outside_bytes is None else usage['accounted_bytes']+self.outside_bytes+additional_bytes+self.safety_margin_bytes
        free=shutil.disk_usage(self.workspace).free
        known=self.outside_bytes is not None
        admitted=known and total<self.limit_bytes and free>=self.min_free_bytes+additional_bytes+self.safety_margin_bytes
        configured=(*self.state_roots,*self.temporary_roots)
        roots_ready=bool(configured) and all(p.is_dir() and p.stat().st_dev==self.workspace.stat().st_dev for p in configured)
        return {'schema_version':1,'kind':'workspace-storage-envelope-audit','mode':'read_only',
            'binding_sha256':self._binding_sha,'workspace_usage':usage,'outside_bytes':self.outside_bytes,
            'additional_reserved_bytes':additional_bytes,'safety_margin_bytes':self.safety_margin_bytes,
            'conservative_accounted_total_bytes':total,'strict_limit_bytes':self.limit_bytes,'comparison':'strictly_less_than',
            'physical_free_bytes':free,'current_admission_passed':bool(admitted),
            'controlled_roots_present_on_workspace_filesystem':roots_ready,
            'controlled_new_file_sink_ready':bool(admitted and roots_ready and hasattr(os,'posix_fallocate')),
            'whole_workspace_write_enforcement_verified':False,'minimum_training_volume_completion_verified':False,
            'remaining_uncontrolled_writers':['existing_SQLite_transactions_until_integrated','installers','unwrapped_logs_or_other_processes'],
            'training_started':False,'training_authorized':False,'deletes_existing_data':False}

    def guard(self,additional_bytes=0):
        report=self.audit(additional_bytes)
        if not report['current_admission_passed']:
            raise StorageEnvelopeExceeded('storage budget is unknown or cannot admit the next controlled operation')
        return report

    def require_controlled_directory(self, value):
        """Read-only coverage check before a model/game can modify state."""
        self._check()
        path = self._inside(value)
        if not any(path.is_relative_to(root) for root in (*self.state_roots, *self.temporary_roots)):
            raise ContractError('state directory is outside the declared controlled storage roots')
        existing = path
        while not existing.exists(): existing = existing.parent
        if not existing.is_dir() or existing.stat().st_dev != self.workspace.stat().st_dev:
            raise ContractError('controlled state directory requires the workspace filesystem')
        return path

    def _target(self,value):
        path=self._inside(value)
        roots=(*self.state_roots,*self.temporary_roots)
        if (not any(path.is_relative_to(p) and path!=p for p in roots) or path.is_relative_to(self.control)
                or not path.parent.is_dir() or path.exists() or path.is_symlink()):
            raise ContractError('new file inside an existing explicit state/temp directory required')
        if path.parent.stat().st_dev!=self.workspace.stat().st_dev:
            raise ContractError('controlled file reservation requires the workspace filesystem')
        return path

    def _initialize_control(self):
        self._inside(self.control)
        owner=self.control/'owner.json'
        if not self.control.exists():
            self.control.mkdir(parents=True)
            with owner.open('x',encoding='utf-8') as out:
                out.write(canonical_json({'binding':self.binding,'binding_sha256':self._binding_sha})+'\n');out.flush();os.fsync(out.fileno())
        if (owner.is_symlink() or not owner.is_file() or
                digest(read_json(owner))!=digest({'binding':self.binding,'binding_sha256':self._binding_sha})):
            raise ContractError('storage control directory is unowned or belongs to another binding')

    @contextmanager
    def _locked(self):
        self._initialize_control()
        lock=self.control/'reservation.lock'
        if lock.is_symlink():raise ContractError('storage reservation lock cannot be a symlink')
        with lock.open('a+b') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            try:self._check();yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def reserve_file(self,reservation_id,target,max_bytes,*,purpose='checkpoint'):
        """Explicit allocation only; failed/incomplete reservations stay visible.

        Physically reserving the maximum payload avoids optimistic sparse-file
        promises. No big reservation is made by audit/default construction.
        """
        identifier(reservation_id);integer(max_bytes,'maximum controlled file payload',1,self.limit_bytes)
        if purpose not in ('checkpoint','trajectory','temporary','log','data_index','environment'):
            raise ContractError('explicit controlled-file purpose required')
        if not hasattr(os,'posix_fallocate'):raise ContractError('physical reservation unavailable on this platform')
        target=self._target(target)
        block=max(1,os.statvfs(self.workspace).f_frsize)
        reserve=((max_bytes+block-1)//block)*block+8*block
        self.guard(reserve)  # Even control metadata is refused before admission.
        with self._locked():
            target=self._target(target);self.guard(reserve)
            part=self.control/(reservation_id+'.part');record=self.control/(reservation_id+'.json')
            if any(p.exists() or p.is_symlink() for p in (part,record,self.control/(reservation_id+'.complete.json'))):
                raise ContractError('reservation id already exists; inspect it rather than retrying automatically')
            metadata={'schema_version':1,'kind':'bounded-file-reservation-v1','binding_sha256':self._binding_sha,
                'reservation_id':reservation_id,'target':target.relative_to(self.workspace).as_posix(),
                'max_payload_bytes':max_bytes,'purpose':purpose,'part_name':part.name}
            with record.open('x',encoding='utf-8') as out:
                out.write(canonical_json(metadata)+'\n');out.flush();os.fsync(out.fileno())
            file=part.open('x+b',buffering=0)
            try:
                os.posix_fallocate(file.fileno(),0,max_bytes)
                os.fsync(file.fileno());self.guard()
            except BaseException:
                file.close()  # Retain allocation and metadata after uncertainty.
                raise
            return ReservedFile(self,file,part,record,target,metadata)


class ReservedFile:
    """File-like bounded payload sink; only explicit commit publishes output."""
    def __init__(self,envelope,file,part,record,target,metadata):
        self.envelope,self._file=envelope,file
        self.part,self.record,self.target=part,record,target
        self.metadata=deepcopy(metadata);self._metadata_sha=digest(metadata)
        st=os.fstat(file.fileno());self._inode=(st.st_dev,st.st_ino)
        self.max_bytes=metadata['max_payload_bytes'];self._written=0;self._failed=False;self._receipt=None

    def _check(self):
        if self._file.closed or self._failed or self._receipt is not None:raise ContractError('bounded sink is closed, failed or already committed')
        self.envelope._check();self.envelope._inside(self.part)
        st=self.part.stat();opened=os.fstat(self._file.fileno())
        integer(self._written,'bounded logical payload size',0,self.max_bytes)
        if ((st.st_dev,st.st_ino)!=self._inode or (opened.st_dev,opened.st_ino)!=self._inode or
                st.st_size!=self.max_bytes or self.max_bytes!=self.metadata['max_payload_bytes'] or
                self.target!=self.envelope.workspace/self.metadata['target'] or
                self.part!=self.envelope.control/self.metadata['part_name'] or
                self.record!=self.envelope.control/(self.metadata['reservation_id']+'.json') or self.record.is_symlink() or
                digest(read_json(self.record))!=self._metadata_sha or digest(self.metadata)!=self._metadata_sha):
            raise ContractError('physical reservation identity changed')

    def write(self,data):
        self._check()
        if not isinstance(data,(bytes,bytearray,memoryview)):raise ContractError('bounded file accepts binary payload only')
        size=memoryview(data).nbytes
        if self._file.tell()+size>self.max_bytes:
            self._failed=True;raise StorageEnvelopeExceeded('controlled file payload exceeds its physical reservation')
        # Capacity is already physically reserved. Re-censusing the entire
        # workspace for each small torch serialization write is unnecessary;
        # full guard runs at allocation, flush and publication boundaries.
        try:n=self._file.write(data)
        except BaseException:
            self._failed=True;raise
        if n!=size:self._failed=True;raise OSError('partial controlled write retained for inspection')
        self._written=max(self._written,self._file.tell());return n

    def tell(self):self._check();return self._file.tell()

    def seek(self,offset,whence=0):
        self._check()
        if type(offset) is not int or type(whence) is not int or whence not in (0,1,2):raise ContractError('bounded seek requires integer offset/mode')
        position=offset+(self._file.tell() if whence==1 else self._written if whence==2 else 0)
        if not 0<=position<=self.max_bytes:raise StorageEnvelopeExceeded('controlled seek exceeds reservation')
        return self._file.seek(position)

    def truncate(self,size=None):
        self._check();size=self._file.tell() if size is None else size
        integer(size,'bounded logical truncation',0,self.max_bytes)
        # Erase a truncated tail without releasing its physical reservation;
        # a later seek/write must see zeroes, not stale prior payload bytes.
        position=self._file.tell()
        try:
            if size<self._written:
                self._file.seek(size);remaining=self._written-size
                while remaining:
                    count=min(remaining,64*1024)
                    if self._file.write(b'\0'*count)!=count:raise OSError('partial bounded truncation')
                    remaining-=count
            self._file.seek(position)
        except BaseException:
            self._failed=True;raise
        self._written=size;return size

    def flush(self):
        self._check();self.envelope.guard()
        try:self._file.flush();os.fsync(self._file.fileno())
        except BaseException:
            self._failed=True;raise

    def commit(self):
        if self._receipt is not None:return deepcopy(self._receipt)
        self._check()
        with self.envelope._locked():
            self._check();self.envelope._target(self.target)
            self.envelope.guard(2*max(1,os.statvfs(self.envelope.workspace).f_frsize))
            self._file.truncate(self._written);self._file.flush();os.fsync(self._file.fileno())
            sha=_hash(self.part)
            # Atomic no-overwrite publication; the source reservation is our own
            # newly allocated file. Existing user destinations are never replaced.
            os.link(self.part,self.target,follow_symlinks=False)
            receipt={'kind':'committed-bounded-file-v1','reservation_id':self.metadata['reservation_id'],
                'path':self.metadata['target'],'artifact_bytes':self._written,'artifact_sha256':sha,
                'max_payload_bytes':self.max_bytes,'purpose':self.metadata['purpose'],'binding_sha256':self.envelope._binding_sha}
            complete=self.envelope.control/(self.metadata['reservation_id']+'.complete.json')
            with complete.open('x',encoding='utf-8') as out:
                out.write(canonical_json(receipt)+'\n');out.flush();os.fsync(out.fileno())
            self._file.close();self.part.unlink()  # Never any pre-existing file.
            self._receipt=receipt
            self.envelope.guard()
            return deepcopy(receipt)

    def close(self):
        if not self._file.closed:self._file.close()  # Leave .part and receipt.

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
