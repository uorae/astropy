# Licensed under a 3-clause BSD style license - see LICENSE.rst


import numpy as np
import pytest

from astropy import constants
from astropy import units as u
from astropy.coordinates import (
    CartesianDifferential,
    CartesianRepresentation,
    DynamicMatrixTransform,
    FunctionTransformWithFiniteDifference,
    SphericalDifferential,
    SphericalRepresentation,
    TimeAttribute,
    get_sun,
)
from astropy.coordinates.baseframe import frame_transform_graph
from astropy.coordinates.builtin_frames import FK5, GCRS, ICRS, LSR, AltAz, Galactic
from astropy.coordinates.builtin_frames.galactic_transforms import (
    _gal_to_fk5,
    fk5_to_gal,
)
from astropy.coordinates.sites import get_builtin_sites
from astropy.time import Time
from astropy.units import allclose as quantity_allclose


@pytest.mark.parametrize("dt", [1 * u.second, 1 * u.year])
@pytest.mark.parametrize("symmetric", [True, False])
def test_faux_lsr(dt, symmetric):
    J2000 = Time("J2000")

    class LSR2(LSR):
        obstime = TimeAttribute(default=J2000)

    @frame_transform_graph.transform(
        FunctionTransformWithFiniteDifference,
        ICRS,
        LSR2,
        finite_difference_dt=dt,
        symmetric_finite_difference=symmetric,
    )
    def icrs_to_lsr(icrs_coo, lsr_frame):
        offset = lsr_frame.v_bary * (lsr_frame.obstime - J2000)
        return lsr_frame.realize_frame(icrs_coo.data.without_differentials() + offset)

    @frame_transform_graph.transform(
        FunctionTransformWithFiniteDifference,
        LSR2,
        ICRS,
        finite_difference_dt=dt,
        symmetric_finite_difference=symmetric,
    )
    def lsr_to_icrs(lsr_coo, icrs_frame):
        offset = lsr_coo.v_bary * (lsr_coo.obstime - J2000)
        return icrs_frame.realize_frame(lsr_coo.data - offset)

    common_coords = {
        "dec": 45.6 * u.deg,
        "distance": 7.8 * u.au,
        "pm_ra_cosdec": 0 * u.marcsec / u.yr,
    }
    ic = ICRS(
        ra=12.3 * u.deg,
        pm_dec=0 * u.marcsec / u.yr,
        radial_velocity=0 * u.km / u.s,
        **common_coords,
    )
    lsrc = ic.transform_to(LSR2())

    assert quantity_allclose(ic.cartesian.xyz, lsrc.cartesian.xyz)

    idiff = ic.cartesian.differentials["s"]
    ldiff = lsrc.cartesian.differentials["s"]
    totchange = np.sum((ldiff.d_xyz - idiff.d_xyz) ** 2) ** 0.5
    assert quantity_allclose(totchange, np.sum(lsrc.v_bary.d_xyz**2) ** 0.5)

    ic2 = ICRS(
        ra=120.3 * u.deg,
        pm_dec=10 * u.marcsec / u.yr,
        radial_velocity=1000 * u.km / u.s,
        **common_coords,
    )
    lsrc2 = ic2.transform_to(LSR2())
    ic2_roundtrip = lsrc2.transform_to(ICRS())

    tot = np.sum(lsrc2.cartesian.differentials["s"].d_xyz ** 2) ** 0.5
    assert np.abs(tot.to("km/s") - 1000 * u.km / u.s) < 20 * u.km / u.s

    assert quantity_allclose(ic2.cartesian.xyz, ic2_roundtrip.cartesian.xyz)


def test_faux_fk5_galactic():
    class Galactic2(Galactic):
        pass

    dt = 1000 * u.s

    @frame_transform_graph.transform(
        FunctionTransformWithFiniteDifference,
        FK5,
        Galactic2,
        finite_difference_dt=dt,
        symmetric_finite_difference=True,
        finite_difference_frameattr_name=None,
    )
    def fk5_to_gal2(fk5_coo, gal_frame):
        return DynamicMatrixTransform(fk5_to_gal, FK5, Galactic2)(fk5_coo, gal_frame)

    @frame_transform_graph.transform(
        FunctionTransformWithFiniteDifference,
        Galactic2,
        ICRS,
        finite_difference_dt=dt,
        symmetric_finite_difference=True,
        finite_difference_frameattr_name=None,
    )
    def gal2_to_fk5(gal_coo, fk5_frame):
        return DynamicMatrixTransform(_gal_to_fk5, Galactic2, FK5)(gal_coo, fk5_frame)

    c1 = FK5(
        ra=150 * u.deg,
        dec=-17 * u.deg,
        radial_velocity=83 * u.km / u.s,
        pm_ra_cosdec=-41 * u.mas / u.yr,
        pm_dec=16 * u.mas / u.yr,
        distance=150 * u.pc,
    )
    c2 = c1.transform_to(Galactic2())
    c3 = c1.transform_to(Galactic())

    # compare the matrix and finite-difference calculations
    assert quantity_allclose(c2.pm_l_cosb, c3.pm_l_cosb, rtol=1e-4)
    assert quantity_allclose(c2.pm_b, c3.pm_b, rtol=1e-4)


def test_gcrs_diffs():
    time = Time("2017-01-01")
    gf = GCRS(obstime=time)
    sung = get_sun(time)  # should have very little vhelio

    # qtr-year off sun location should be the direction of ~ maximal vhelio
    qtrsung = get_sun(time - 0.25 * u.year)

    # now we use those essentially as directions where the velocities should
    # be either maximal or minimal - with or perpendiculat to Earh's orbit
    msungr = CartesianRepresentation(-sung.cartesian.xyz).represent_as(
        SphericalRepresentation
    )
    common_coords = {
        "distance": 100 * u.au,
        "pm_ra_cosdec": 0 * u.marcsec / u.yr,
        "pm_dec": 0 * u.marcsec / u.yr,
        "radial_velocity": 0 * u.km / u.s,
    }
    suni = ICRS(ra=msungr.lon, dec=msungr.lat, **common_coords)
    qtrsuni = ICRS(ra=qtrsung.ra, dec=qtrsung.dec, **common_coords)

    # Now we transform those parallel- and perpendicular-to Earth's orbit
    # directions to GCRS, which should shift the velocity to either include
    # the Earth's velocity vector, or not (for parallel and perpendicular,
    # respectively).
    sung = suni.transform_to(gf)
    qtrsung = qtrsuni.transform_to(gf)

    # should be high along the ecliptic-not-sun sun axis and
    # low along the sun axis
    assert 30 * u.km / u.s < np.abs(qtrsung.radial_velocity) < 40 * u.km / u.s
    assert np.abs(sung.radial_velocity) < 1 * u.km / u.s

    suni2 = sung.transform_to(ICRS())
    assert np.all(np.abs(suni2.data.differentials["s"].d_xyz) < 3e-5 * u.km / u.s)
    qtrisun2 = qtrsung.transform_to(ICRS())
    assert np.all(np.abs(qtrisun2.data.differentials["s"].d_xyz) < 3e-5 * u.km / u.s)


def test_altaz_diffs():
    time = Time("J2015") + np.linspace(-1, 1, 1000) * u.day
    aa = AltAz(obstime=time, location=get_builtin_sites()["greenwich"])

    icoo = ICRS(
        np.zeros(time.shape) * u.deg,
        10 * u.deg,
        100 * u.au,
        pm_ra_cosdec=np.zeros(time.shape) * u.marcsec / u.yr,
        pm_dec=0 * u.marcsec / u.yr,
        radial_velocity=0 * u.km / u.s,
    )

    acoo = icoo.transform_to(aa)

    # Make sure the change in radial velocity over ~2 days isn't too much
    # more than the rotation speed of the Earth - some excess is expected
    # because the orbit also shifts the RV, but it should be pretty small
    # over this short a time.
    assert (
        np.ptp(acoo.radial_velocity) / 2 < (2 * np.pi * constants.R_earth / u.day) * 1.2
    )  # MAGIC NUMBER

    cdiff = acoo.data.differentials["s"].represent_as(CartesianDifferential, acoo.data)

    # The "total" velocity should be > c, because the *tangential* velocity
    # isn't a True velocity, but rather an induced velocity due to the Earth's
    # rotation at a distance of 100 AU
    assert np.all(np.sum(cdiff.d_xyz**2, axis=0) ** 0.5 > constants.c)


_xfail = pytest.mark.xfail


@pytest.mark.parametrize(
    "distance",
    [
        1000 * u.au,
        10 * u.pc,
        pytest.param(10 * u.kpc, marks=_xfail),
        pytest.param(100 * u.kpc, marks=_xfail),
    ],
)
# TODO:  make these not fail when the
# finite-difference numerical stability
# is improved
def test_numerical_limits(distance):
    """
    Tests the numerical stability of the default settings for the finite
    difference transformation calculation.  This is *known* to fail for at
    >~1kpc, but this may be improved in future versions.
    """
    gcrs_coord = ICRS(
        ra=0 * u.deg,
        dec=10 * u.deg,
        distance=distance,
        pm_ra_cosdec=0 * u.marcsec / u.yr,
        pm_dec=0 * u.marcsec / u.yr,
        radial_velocity=0 * u.km / u.s,
    ).transform_to(GCRS(obstime=Time("J2017") + np.linspace(-0.5, 0.5, 100) * u.year))

    # if its a lot bigger than this - ~the maximal velocity shift along
    # the direction above with a small allowance for noise - finite-difference
    # rounding errors have ruined the calculation
    assert np.ptp(gcrs_coord.radial_velocity) < 65 * u.km / u.s


def diff_info_plot(frame, time):
    """
    Useful for plotting a frame with multiple times. *Not* used in the testing
    suite per se, but extremely useful for interactive plotting of results from
    tests in this module.
    """
    from matplotlib import pyplot as plt

    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(20, 12))
    ax1.plot_date(
        time.plot_date, frame.data.differentials["s"].d_xyz.to(u.km / u.s).T, fmt="-"
    )
    ax1.legend(["x", "y", "z"])

    ax2.plot_date(
        time.plot_date,
        np.sum(frame.data.differentials["s"].d_xyz.to(u.km / u.s) ** 2, axis=0) ** 0.5,
        fmt="-",
    )
    ax2.set_title("total")

    sd = frame.data.differentials["s"].represent_as(SphericalDifferential, frame.data)

    ax3.plot_date(time.plot_date, sd.d_distance.to(u.km / u.s), fmt="-")
    ax3.set_title("radial")

    ax4.plot_date(time.plot_date, sd.d_lat.to(u.marcsec / u.yr), fmt="-", label="lat")
    ax4.plot_date(time.plot_date, sd.d_lon.to(u.marcsec / u.yr), fmt="-", label="lon")

    return fig
