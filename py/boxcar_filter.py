#!/usr/bin/env python

"""get_sd_data.py: module is dedicated to fetch fitacf data from files."""

__author__ = "Chakraborty, S."
__copyright__ = "Copyright 2020, SuperDARN@VT"
__credits__ = []
__license__ = "MIT"
__version__ = "1.0."
__maintainer__ = "Chakraborty, S."
__email__ = "shibaji7@vt.edu"
__status__ = "Research"

import copy
import numpy as np
from scipy import stats
from scipy import signal
from scipy.stats import beta
import pandas as pd

import multiprocessing as mp
from functools import partial

from get_fit_data import Gate, Beam, Scan, FetchData
import fit_utils

def create_gaussian_weights(mu, sigma, _kernel=3, base_w=5):
    """
    Method used to create gaussian weights
    mu: n 1D list of all mean values
    sigma: n 1D list of sigma matrix
    """
    _k = (_kernel-1)/2
    _kNd = np.zeros((3,3,3))
    for i in range(_kernel):
        for j in range(_kernel):
            for k in range(_kernel):
                _kNd[i,j,k] = np.exp(-((float(i-_k)**2/(2*sigma[0]**2)) + (float(j-_k)**2/(2*sigma[1]**2)) + (float(k-_k)**2/(2*sigma[2]**2))))
    _kNd = np.floor(_kNd * base_w).astype(int)
    return _kNd


class Filter(object):
    """Class to filter data - Boxcar median filter."""

    def __init__(self, thresh=.7, w=None, pbnd=[1./5., 4./5.], pth=0.25, kde_plot_point=(6,20), verbose=False):
        """
        initialize variables
        thresh: Threshold of the weight matrix
        w: Weight matrix
        pbnd: Lower and upper bounds of IS / GS probability
        pth: Probability of the threshold
        kde_plot_point: Plot the distribution for a point with (beam, gate)
        """
        self.thresh = thresh
        if w is None: w = np.array([[[1,2,1],[2,3,2],[1,2,1]],
                                    [[2,3,2],[3,5,3],[2,3,2]],
                                    [[1,2,1],[2,3,2],[1,2,1]]])
        self.w = w
        self.pbnd = pbnd
        self.pth = pth
        self.kde_plot_point = kde_plot_point
        self.verbose = verbose
        return

    def _discard_repeting_beams(self, scan, ch=True):
        """
        Discard all more than one repeting beams
        scan: SuperDARN scan
        """
        oscan = Scan(scan.stime, scan.etime, scan.stype)
        if ch: scan.beams = sorted(scan.beams, key=lambda bm: (bm.bmnum))
        else: scan.beams = sorted(scan.beams, key=lambda bm: (bm.bmnum, bm.time))
        bmnums = []
        for bm in scan.beams:
            if bm.bmnum not in bmnums:
                if hasattr(bm, "slist") and len(getattr(bm, "slist")) > 0:
                    oscan.beams.append(bm)
                    bmnums.append(bm.bmnum)
        oscan.update_time()
        oscan.beams = sorted(oscan.beams, key=lambda bm: bm.bmnum)
        return oscan
    
    def doAJFilter(self, i_scans, comb=False):
        """ Run default AJ's filter """
        if comb: 
            scans = []
            for s in i_scans:
                scans.append(self._discard_repeting_beams(s))
        else: scans = i_scans
        self.scans = scans
        
        w = self.w
        oscan = Scan(scans[1].stime, scans[1].etime, scans[1].stype)
        if w is None: w = np.array([[[1,2,1],[2,3,2],[1,2,1]],
                                [[2,3,2],[3,5,3],[2,3,2]],
                                [[1,2,1],[2,3,2],[1,2,1]]])
        l_bmnum, r_bmnum = scans[1].beams[0].bmnum, scans[1].beams[-1].bmnum
    
        for b in scans[1].beams:
            bmnum = b.bmnum
            beam = Beam()
            beam.copy(b)
    
            for key in beam.__dict__.keys():
                if type(getattr(beam, key)) == np.ndarray: setattr(beam, key, [])
    
            for r in range(0,b.nrang):
                box = [[[None for j in range(3)] for k in range(3)] for n in range(3)]
    
                for j in range(0,3):# iterate through time
                    for k in range(-1,2):# iterate through beam
                        for n in range(-1,2):# iterate through gate
                            # get the scan we are working on
                            s = scans[j]
                            if s == None: continue
                            # get the beam we are working on
                            if s == None: continue
                            # get the beam we are working on
                            tbm = None
                            for bm in s.beams:
                                if bm.bmnum == bmnum + k: tbm = bm
                            if tbm == None: continue
                            # check if target gate number is in the beam
                            if r+n in tbm.slist:
                                ind = np.array(tbm.slist).tolist().index(r + n)
                                box[j][k+1][n+1] = Gate(tbm, ind, gflg_type=-1)
                            else: box[j][k+1][n+1] = 0
                pts = 0.0
                tot = 0.0
                v,w_l,p_l,gfx = list(), list(), list(), list()
        
                for j in range(0,3):# iterate through time
                    for k in range(0,3):# iterate through beam
                        for n in range(0,3):# iterate through gate
                            bx = box[j][k][n]
                            if bx == None: continue
                            wt = w[j][k][n]
                            tot += wt
                            if bx != 0:
                                pts += wt
                                for m in range(0, wt):
                                    v.append(bx.v)
                                    w_l.append(bx.w_l)
                                    p_l.append(bx.p_l)
                                    gfx.append(bx.gflg)
                if pts / tot >= self.thresh:# check if we meet the threshold
                    beam.slist.append(r)
                    beam.v.append(np.median(v))
                    beam.w_l.append(np.median(w_l))
                    beam.p_l.append(np.median(p_l))
                    
                    # Re-evaluate the groundscatter flag using old method
                    gflg = 0 if np.median(w_l) > -3.0 * np.median(v) + 90.0 else 1
                    beam.gflg.append(gflg)
                    
            oscan.beams.append(beam)
    
        oscan.update_time()
        sorted(oscan.beams, key=lambda bm: bm.time)
        return oscan


    def doFilter(self, i_scans, comb=False, plot_kde=False, gflg_type=-1):
        """
        Median filter based on the weight given by matrix (3X3X3) w, and threshold based on thresh
    
        i_scans: 3 consecutive radar scans
        comb: combine beams
        plot_kde: plot KDE estimate for the range cell if true
        gflg_type: Type of gflag used in this study [-1, 0, 1, 2] -1 is default other numbers are listed in
                    Evan's presentation.
        """
        if comb: 
            scans = []
            for s in i_scans:
                scans.append(self._discard_repeting_beams(s))
        else: scans = i_scans

        self.scans = scans
        w, pbnd, pth, kde_plot_point = self.w, self.pbnd, self.pth, self.kde_plot_point
        oscan = Scan(scans[1].stime, scans[1].etime, scans[1].stype)
        if w is None: w = np.array([[[1,2,1],[2,3,2],[1,2,1]],
                                [[2,3,2],[3,5,3],[2,3,2]],
                                [[1,2,1],[2,3,2],[1,2,1]]])
        l_bmnum, r_bmnum = scans[1].beams[0].bmnum, scans[1].beams[-1].bmnum
    
        for b in scans[1].beams:
            bmnum = b.bmnum
            beam = Beam()
            beam.copy(b)
    
            for key in beam.__dict__.keys():
                if type(getattr(beam, key)) == np.ndarray: setattr(beam, key, [])

            setattr(beam, "v_mad", [])
            setattr(beam, "gflg_conv", [])
            setattr(beam, "gflg_kde", [])
    
            for r in range(0,b.nrang):
                box = [[[None for j in range(3)] for k in range(3)] for n in range(3)]
    
                for j in range(0,3):# iterate through time
                    for k in range(-1,2):# iterate through beam
                        for n in range(-1,2):# iterate through gate
                            # get the scan we are working on
                            s = scans[j]
                            if s == None: continue
                            # get the beam we are working on
                            if s == None: continue
                            # get the beam we are working on
                            tbm = None
                            for bm in s.beams:
                                if bm.bmnum == bmnum + k: tbm = bm
                            if tbm == None: continue
                            # check if target gate number is in the beam
                            if r+n in tbm.slist:
                                ind = np.array(tbm.slist).tolist().index(r + n)
                                box[j][k+1][n+1] = Gate(tbm, ind, gflg_type=gflg_type)
                            else: box[j][k+1][n+1] = 0
                pts = 0.0
                tot = 0.0
                v,w_l,p_l,gfx = list(), list(), list(), list()
        
                for j in range(0,3):# iterate through time
                    for k in range(0,3):# iterate through beam
                        for n in range(0,3):# iterate through gate
                            bx = box[j][k][n]
                            if bx == None: continue
                            wt = w[j][k][n]
                            tot += wt
                            if bx != 0:
                                pts += wt
                                for m in range(0, wt):
                                    v.append(bx.v)
                                    w_l.append(bx.w_l)
                                    p_l.append(bx.p_l)
                                    gfx.append(bx.gflg)
                if pts / tot >= self.thresh:# check if we meet the threshold
                    beam.slist.append(r)
                    beam.v.append(np.median(v))
                    beam.w_l.append(np.median(w_l))
                    beam.p_l.append(np.median(p_l))
                    beam.v_mad.append(np.median(np.abs(np.array(v)-np.median(v))))
                    
                    # Re-evaluate the groundscatter flag using old method
                    gflg = 0 if np.median(w_l) > -3.0 * np.median(v) + 90.0 else 1
                    beam.gflg.append(gflg)
                    
                    # Re-evaluate the groundscatter flag using weight function
                    #if bmnum == 12: print(bmnum,"-",r,":(0,1)->",len(gfx)-np.count_nonzero(gfx),np.count_nonzero(gfx),np.nansum(gfx) / tot)
                    gflg = np.nansum(gfx) / tot
                    if np.nansum(gfx) / tot <= pbnd[0]: gflg=0.
                    elif np.nansum(gfx) / tot >= pbnd[1]: gflg=1.
                    else: gflg=2.
                    beam.gflg_conv.append(gflg)
    
                    # KDE estimation using scipy Beta(a, b, loc=0, scale=1)
                    _gfx = np.array(gfx).astype(float)
                    _gfx[_gfx==0], _gfx[_gfx==1]= np.random.uniform(low=0.01, high=0.05, size=len(_gfx[_gfx==0])), np.random.uniform(low=0.95, high=0.99, size=len(_gfx[_gfx==1]))
                    a, b, loc, scale = beta.fit(_gfx, floc=0., fscale=1.)
                    if kde_plot_point is not None:
                        if (kde_plot_point[0] == bmnum) and (kde_plot_point[1] == r):
                            #if plot_kde: plot_kde_distribution(a, b, loc, scale, pth, pbnd)
                            pass
                    gflg = 1 - beta.cdf(pth, a, b, loc=0., scale=1.)
                    if gflg <= pbnd[0]: gflg=0.
                    elif gflg >= pbnd[1]: gflg=1.
                    else: gflg=2.
                    beam.gflg_kde.append(gflg)
            oscan.beams.append(beam)
    
        oscan.update_time()
        sorted(oscan.beams, key=lambda bm: bm.bmnum)
        return oscan
    

def doAJFilter(rad, start_date, end_date, file_type="fitacf", out_file_dir="/tmp/", scan_prop={"dur": 1, "stype": "normal"}, thresh=0.4):
    """ AJ's Filter """
    io = FetchData(rad, [start_date, end_date], ftype=file_type, verbose=True)
    _, scans = io.fetch_data(by="scan", scan_prop=scan_prop)
    fscans = []
    ajfilter = Filter(thresh=thresh)
    for i in range(1,len(scans)-2):
        print(" Time:", scans[i].stime)
        i_scans = scans[i-1:i+2]
        fscans.append(ajfilter.doAJFilter(i_scans, comb=True))
    fname = out_file_dir + "medfilt.{rad}.{start}.{end}.csv".format(rad=rad, start=start_date.strftime("%Y%m%d-%H%M"),
                                                                          end=end_date.strftime("%Y%m%d-%H%M"))
    fit_utils.save_to_csv(fname, scans=fscans)
    fit_utils.save_to_netcdf(fname.replace(".csv", ".nc"), fscans, thresh)
    return

def doFilter(scans, thresh=0.4, cores=24):
    fscans, mScans = [], []
    ajfilter = Filter(thresh=thresh)
    p0 = mp.Pool(cores)
    partial_filter = partial(ajfilter.doFilter, gflg_type=-1)
    for i in range(1,len(scans)-2):
        mScans.append(scans[i-1:i+2])
    j = 0
    for s in p0.map(partial_filter, mScans):
        if np.mod(j,10)==0: print(" Running median filter for scan at - ", scans[i].stime)
        fscans.append(s)
        j += 1
    return fscans
