import re
import xarray as xr
import numpy as np
import pandas as pd
from unitpy import Unit
import trosat.sunpos as sp

# import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
import matplotlib.dates as mdates

from mordor.qcrad import SNAMES, CONSTANTS
import mordor.utils
import mordor.futils

class CMAPS:
    ghi = plt.cm.Blues
    dni = plt.cm.RdPu
    dhi = plt.cm.Greens
    lwd = plt.cm.Greys
    tair = plt.cm.Reds
    pair = plt.cm.Blues
    rh = plt.cm.Greys
    tdew = plt.cm.Reds
    twb = plt.cm.Reds
    tsens = plt.cm.Reds
    freq = plt.cm.Greys

class LABELS:
    ghi = 'GHI'
    dhi = 'DHI'
    dni = 'DNI'
    lwd = 'LWD'
    tair = 'air temperature'
    pair = 'air pressure'
    rh = 'relative humidity'
    tdew = 'dew point temperature'
    twb = 'wet bulb temperature'
    tsens = 'sensor temperature'
    freq = 'ventilator frequency'

@xr.register_dataset_accessor("quicklooks")
class MORDORQuicklooks:
    """
    MORDOR quicklooks
    """
    def __init__(self, xarray_obj):
        self.ds = xarray_obj
        self.time = pd.to_datetime(self.ds.time)

        # retrieve solar zenith angle from data
        szen = None
        for var in xarray_obj.filter_by_attrs(standard_name="solar_zenith_angle"):
            szen = xarray_obj[var].values * Unit(xarray_obj[var].attrs["units"])
            break
        # calculate solar zenith angle if not in data
        if szen is None:
            for var in xarray_obj.filter_by_attrs(standard_name="latitude"):
                lat = xarray_obj[var].values
                break
            for var in xarray_obj.filter_by_attrs(standard_name="longitude"):
                lon = xarray_obj[var].values
                break
            assert lat is not None
            assert lon is not None
            szen, _ = sp.sun_angles(xarray_obj.time.values, lat=lat, lon=lon) * Unit("degrees")

        mu0 = np.cos(szen.to("radian").value)
        mu0[mu0 < 0] = 0  # exclude night
        self.mu0 = mu0
        self.szen = szen.value

    def _filter_device(self, *, ids=None, standard_names=None):
        if ids is None and standard_names is None:
            return 0

        if standard_names is None:
            dsname = self.ds
        else:
            for i, sname in enumerate(standard_names):
                if i == 0:
                    dsname = self.ds.filter_by_attrs(standard_name=sname)
                else:
                    dsname = xr.merge((dsname, self.ds.filter_by_attrs(standard_name=sname)))

        if ids is None:
            return dsname
        else:
            for i, id in enumerate(ids):
                if i == 0:
                    dsout = dsname.filter_by_attrs(troposID=id)
                else:
                    dsout = xr.merge((dsout, dsname.filter_by_attrs(troposID=id)))
            return dsout

    def time_series(self, key=None, *, ax=None, ids=None, freq=None, unit=None, scale=1., add_offset=0., standard_names=None, label="", device=False, cmap=None, kwargs={}):
        if ax is None:
            ax = plt.gca()

        if key is None:
            dsp = self._filter_device(ids=ids, standard_names=standard_names)
        else:
            standard_names = [getattr(SNAMES, key)]
            dsp = self._filter_device(ids=ids, standard_names=standard_names)
            cmap = getattr(CMAPS, key)
            label = getattr(LABELS, key)

        if freq is not None:
            dsp = mordor.futils.resample(dsp, freq=freq)

        if cmap is not None:
            ax.set_prop_cycle(color=cmap(np.linspace(0.9, 0.4, len(dsp.keys()))))

        plots = []
        for var in dsp:
            if device:
                device = dsp[var].attrs["device"].split(',')[0]
                device = re.sub("\s+", "\n", device)
                id = dsp[var].attrs["troposID"]
                varlabel = f"{label}\n{device}\n{id}"
            else:
                varlabel = label
            values = dsp[var].values if unit is None else (dsp[var].values*Unit(dsp[var].attrs['units'])).to(unit).value
            values *= scale
            values += add_offset
            pl, = ax.plot(dsp.time.values, values, label=varlabel, **kwargs)
            plots.append(pl)

        return plots

    def flux(self, ax=None, ids=None, device=False, legend=True, kwargs={}):
        if ax is None:
            ax = plt.gca()

        plots = []

        pl = self.time_series("ghi", ids=ids, device=device, ax=ax, kwargs=kwargs)
        plots += pl

        pl = self.time_series("dhi", ids=ids, device=device, ax=ax, kwargs=kwargs)
        plots += pl

        dsp = self._filter_device(ids=ids, standard_names=[SNAMES.dni])
        ax.set_prop_cycle(color=CMAPS.dni(np.linspace(0.9, 0.1, len(dsp.keys()))))
        for var in dsp:
            label = r"$\mu_0$DNI, "+self.ds[var].attrs["device"] if device else r"$\mu_0$DNI"
            pl, = ax.plot(self.time, self.ds[var]*self.mu0, label=label, **kwargs)
            plots.append(pl)

        pl = self.time_series("lwd", ids=ids, device=device, ax=ax, kwargs=kwargs)
        plots += pl

        ax.grid(True)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        ax.set_ylabel("irradiance (W m-2)")
        ax.set_xlabel("time (UTC)")
        if legend:
            ax.legend()
        return plots

    def _set_axis_lim(self, ax, nticks, ylims, base, padding):
        lims = mordor.utils.round_to(base, np.array(ylims))
        tmax = lims[1] if lims[1] >= ylims[1] else lims[1] + padding
        tmin = lims[0] if lims[0] <= ylims[0] else lims[0] - padding
        ax.set_ylim([tmin, tmax])
        ax.set_yticks(np.linspace(tmin, tmax, nticks))
    def meteorology(self, ax=None, ids=None, device=False,legend=True,ylim=None, kwargs={}):
        if ax is None:
            ax = plt.gca()
        if ylim is None:
            ylim = {
                "tair": None,
                "rh": None,
                "pair": None
            }

        plots = []


        pax = ax.twinx()
        rax = ax.twinx()

        pl = self.time_series("tair", ax=ax, ids=ids, device=device,
                              unit='degC',
                              freq='15min',
                              kwargs={'marker': '.', **kwargs})
        tcolor = pl[0].get_color()
        plots += pl
        pl = self.time_series("twb", ax=ax, ids=ids, device=device,
                              unit='degC',
                              freq='15min',
                              kwargs={'ls': '--', **kwargs})
        plots += pl
        pl = self.time_series("tdew", ax=ax, ids=ids, device=device,
                              unit='degC',
                              freq='15min',
                              kwargs={'ls': ':', **kwargs})
        plots += pl
        pl = self.time_series("rh", ax=rax, ids=ids, device=device,
                              scale=100.,
                              freq='15min',
                              kwargs={'marker': 'x', **kwargs})
        rcolor = pl[0].get_color()
        plots += pl
        pl = self.time_series("pair", ax=pax, ids=ids, device=device,
                              unit='hPa',
                              freq='15min',
                              kwargs={'marker': '^', **kwargs})
        pcolor = pl[0].get_color()
        plots += pl

        # set axis limits and ticks for homogenised grid
        if ylim["tair"] is None:
            self._set_axis_lim(ax, nticks=6, ylims=ax.get_ylim(), base=10, padding=5)
        else:
            self._set_axis_lim(ax, nticks=6, ylims=ylim["tair"], base=1, padding=5)
        if ylim["pair"] is None:
            self._set_axis_lim(pax, nticks=6, ylims=pax.get_ylim(), base=10, padding=5)
        else:
            self._set_axis_lim(pax, nticks=6, ylims=ylim["pair"], base=1, padding=5)
        if ylim["rh"] is None:
            self._set_axis_lim(rax, nticks=6, ylims=rax.get_ylim(), base=100, padding=100)
        else:
            self._set_axis_lim(rax, nticks=6, ylims=ylim["rh"], base=1, padding=1)

        ax.grid(True)

        ax.yaxis.set_tick_params(colors=tcolor)
        ax.yaxis.set_label_coords(0.005, 0.005)
        ax.set_yticklabels(
            [f'\n\n{l.get_text()}' for l in ax.get_yticklabels()]
        )

        pax.yaxis.set_label_coords(0.005, 0.005)
        pax.yaxis.set_tick_params(left=True, right=False,
                                  labelleft=True, labelright=False,
                                  colors=pcolor)
        pax.set_yticklabels(
            [f'{l.get_text()}\n\n' for l in pax.get_yticklabels()]
        )
        rax.yaxis.set_label_coords(0.005, 0.005)
        rax.yaxis.set_tick_params(left=True, right=False,
                                  labelleft=True, labelright=False,
                                  colors=rcolor)
        rax.set_yticklabels(
            [f'\n{l.get_text()}\n' for l in rax.get_yticklabels()]
        )

        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        ax.set_ylabel("\n\ntemperature (degC)",ha='left',va='bottom',color=tcolor,rotation='horizontal')
        pax.set_ylabel("pressure (hPa)\n\n",ha='left',va='bottom',color=pcolor,rotation='horizontal')
        rax.set_ylabel("\nrelative humidity (%)\n",ha='left',va='bottom',color=rcolor,rotation='horizontal')
        ax.set_xlabel("time (UTC)")
        if legend:
            ax.legend(
                handles=plots,
                bbox_to_anchor=(1, 1),
                loc='upper left',
                borderaxespad=0.
            )

        return plots, [ax, pax, rax]

    def status(self, ax=None,  ids=None, device=False, kwargs={}):
        if ax is None:
            ax = plt.gca()
        plots = []

        pax = ax.twinx()

        pl = self.time_series("tsens", ax=ax, ids=ids, device=True,
                              unit='degC',
                              freq='15min',
                              kwargs={'marker': '.', **kwargs})
        tcolor = pl[0].get_color()
        plots += pl
        pl = self.time_series("freq", ax=pax, ids=ids, device=True,
                              unit='Hz',
                              freq='15min',
                              kwargs={'ls': '--', **kwargs})
        pcolor = pl[0].get_color()
        plots += pl


        # set axis limits and ticks for homogenised grid
        self._set_axis_lim(ax, nticks=6, ylims=ax.get_ylim(), base=10, padding=5)
        self._set_axis_lim(pax, nticks=6, ylims=pax.get_ylim(), base=10, padding=5)

        ax.grid(True)

        ax.yaxis.set_tick_params(colors=tcolor)
        ax.yaxis.set_label_coords(0.005, 0.005)
        ax.set_yticklabels(
            [f'\n{l.get_text()}' for l in ax.get_yticklabels()]
        )

        pax.yaxis.set_label_coords(0.005, 0.005)
        pax.yaxis.set_tick_params(left=True, right=False,
                                  labelleft=True, labelright=False,
                                  colors=pcolor)
        pax.set_yticklabels(
            [f'{l.get_text()}\n' for l in pax.get_yticklabels()]
        )


        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        ax.set_ylabel("\ntemperature (degC)",ha='left',va='bottom',color=tcolor,rotation='horizontal')
        pax.set_ylabel("frequency (Hz)\n",ha='left',va='bottom',color=pcolor,rotation='horizontal')
        ax.set_xlabel("time (UTC)")
        ax.legend(
            handles=plots,
            bbox_to_anchor=(1, 1),
            loc='upper left',
            borderaxespad=0.
        )

        return plots, [ax, pax]

    def quality_range_shading(self, ax=None, ids=None, ratio=False, kwargs={}):
        kwargs_default = {
            'color': '#b3cde3',
            'edgecolor': 'grey',
            'label': 'Ratio GHI over Sum SW'
        }
        kwargs = {**kwargs_default, **kwargs}

        if ax is None:
            ax = plt.gca()

        Idir = self._filter_device(standard_names=[SNAMES.dni], ids=ids)
        Idir = Idir.to_array(dim='new').mean("new", skipna=True)
        Idir = Idir * self.mu0

        Idif = self._filter_device(standard_names=[SNAMES.dhi], ids=ids)
        Idif = Idif.to_array(dim='new').mean("new", skipna=True)

        sumsw = Idir + Idif
        sumsw[sumsw < 50] = np.nan

        if ratio:
            Ighi = self._filter_device(standard_names=[SNAMES.ghi], ids=ids)
            Ighi = Ighi.to_array(dim='new').mean("new", skipna=True)
            _ = ax.fill_between(
                self.time,
                np.ones(self.time.size)*0.92,
                np.ones(self.time.size)*1.08,
                **kwargs
            )
            pl = ax.plot(self.time, Ighi/sumsw, color='blue', label=r"GHI/($\mu_0$DNI + DHI)")
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
            return pl

        pl = ax.fill_between(self.time, sumsw*0.92, sumsw*1.08, **kwargs)
        return pl

    def quality_range_dhi2ghi(self, ax=None, ids=None, ratio=False, kwargs={}):
        kwargs_default = {
            'color': '#ccebc5',
            'edgecolor': 'grey',
            'label': 'Diffuse ratio test'
        }
        kwargs = {**kwargs_default, **kwargs}

        if ax is None:
            ax = plt.gca()

        Ighi = self._filter_device(standard_names=[SNAMES.ghi], ids=ids)
        Ighi = Ighi.to_array(dim='new').mean("new", skipna=True)

        Idhi = self._filter_device(standard_names=[SNAMES.dhi], ids=ids)
        Idhi = Idhi.to_array(dim='new').mean("new", skipna=True)

        thres_high = np.ones(self.time.size) * 1.10
        thres_high[self.szen < 75.] = 1.05

        if ratio:
            _ = ax.fill_between(
                self.time,
                np.zeros(self.time.size),
                thres_high,
                **kwargs
            )
            pl = ax.plot(self.time, Idhi / Ighi, color='green', label='DHI/GHI')
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
            return pl

        pl = ax.fill_between(self.time, 0, Ighi*thres_high, **kwargs)
        return pl

    def quality_range_lwd2temp(self, ax=None, ids=None, ratio=False, kwargs={}):
        kwargs_default = {
            'color': '#f0f0f0',
            'edgecolor': 'grey',
            'label': 'LWD to Tair comparison'
        }
        kwargs = {**kwargs_default, **kwargs}

        if ax is None:
            ax = plt.gca()

        lwd = self._filter_device(standard_names=[SNAMES.lwd], ids=ids)
        lwd = lwd.to_array(dim='new').mean("new", skipna=True)

        tair = self._filter_device(standard_names=[SNAMES.tair], ids=ids)
        for var in tair:
            tair[var].values = (tair[var].values * Unit(tair[var].attrs['units'])).to("K").value
        tair = tair.to_array(dim='new').mean("new", skipna=True)

        lwd0 = CONSTANTS.k * tair**4
        thres_low = 0.4 * lwd0
        thres_high = 25 + lwd0

        if ratio:
            _ = ax.fill_between(
                self.time,
                0.4,
                1+(25./lwd0),
                **kwargs
            )
            pl = ax.plot(self.time, lwd/lwd0, color='k', label='LWD/(k*Tair^4)')
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
            return pl

        pl = ax.fill_between(self.time, thres_low, thres_high, **kwargs)
        return pl

    def quality_flags(self, ax=None, ids=None, freq='15min', lcolor='grey', cmap=None, fontsize=9, labels=None):
        if ax is None:
            ax = plt.gca()

        if cmap is None:
            cmap = mcolors.ListedColormap(["#f7f7f7", "#f1a340"])

        dsp = self._filter_device(standard_names=[SNAMES.qc], ids=ids)
        N = len(list(dsp.keys()))
        m = 0
        for i, var in enumerate(dsp):
            if labels is None:
                device = dsp[var].attrs["device"].split(',')[0]
                device = re.sub("\s+", "\n", device)
                id = dsp[var].attrs["troposID"]
                label = f"{device}\n{id}"
            else:
                label = labels[i]
            ax.annotate(
                label,
                (-0.01, 0.5 / N + float(i) / N),
                xycoords="axes fraction",
                rotation='vertical',
                va='center', ha='right',
                fontsize=fontsize
            )
            if i != 0:
                ax.axhline(m - 0.5, color=lcolor, lw=2)
            for l in dsp[var].attrs["flag_meanings"].split(" "):
                ax.annotate(
                    l,
                    (1.01, m),
                    xycoords=("axes fraction", "data"),
                    rotation='horizontal',
                    va='center', ha='left',
                    fontsize=8
                )
                m += 1

            qcflag = np.bitwise_and(
                dsp[var].values.astype(int)[:, None],
                np.array([2**i for i in range(6)])
            ).astype(bool)
            if i == 0:
                qcflags = qcflag.copy()
            else:
                qcflags = np.hstack((qcflags, qcflag))

        dsqc = xr.DataArray(
            qcflags,
            dims=('time', 'N'),
            coords={'time': ('time', dsp.time.values)}
        )
        dsqc = dsqc.resample(time=freq).max(skipna=True)

        pl = ax.pcolormesh(dsqc.time, dsqc.N, dsqc.T,
                           cmap=cmap,
                           edgecolors=lcolor, lw=0.5,
                           rasterized=True, snap=True)

        ax.set_yticks(6 * np.arange(1, len(list(dsp.keys()))) - 0.5, [])
        ax.yaxis.set_tick_params(length=40, width=2, color=lcolor, right=True)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        return pl