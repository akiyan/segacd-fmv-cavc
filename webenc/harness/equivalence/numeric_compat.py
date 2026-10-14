"""Native-reference RGB333 constants, independent of source video or decisions.

The native BLAS RGB dot products and scalar Wasm arithmetic round differently.
Rendered codec pixels have only 512 possible colours, so preserve the exact
native values with a fixed lookup instead of a different floating-point result.
"""
import numpy as np


def install(sim,path):
    with np.load(path) as data:
        for name in ['_MD_LUM','_MD_CB','_MD_CR','_F3_DY_LUT','_F3_DC_LUT']:
            setattr(sim,name,data[name].copy())
    class ReferenceVector(np.ndarray):
        __array_priority__=1000
        def __new__(cls,coefficients,table):
            obj=np.asarray(coefficients).view(cls)
            obj.table=table
            return obj
        def __array_finalize__(self,parent):
            if parent is not None:self.table=getattr(parent,'table',None)
        def __array_ufunc__(self,ufunc,method,*inputs,**kwargs):
            if ufunc is np.matmul and method=='__call__' and inputs[1] is self:
                pixels=np.asarray(inputs[0])
                if pixels.shape[-1]==3 and pixels.ndim>=2 and pixels.shape[-2]>=8:
                    levels=pixels/36
                    if np.all(levels==np.floor(levels)) and np.all((levels>=0)&(levels<=7)):
                        index=levels.astype(np.uint16)
                        key=(index[...,0]<<6)|(index[...,1]<<3)|index[...,2]
                        return self.table[key]
            values=tuple(np.asarray(v) if isinstance(v,ReferenceVector) else v for v in inputs)
            return getattr(ufunc,method)(*values,**kwargs)
    sim._LWv=ReferenceVector(sim._LWv,sim._MD_LUM)
    sim._CBv=ReferenceVector(sim._CBv,sim._MD_CB)
    sim._CRv=ReferenceVector(sim._CRv,sim._MD_CR)
