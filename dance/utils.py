import requests
import logging
import numpy as np
from tqdm import tqdm
import healpy as hp
import matplotlib.pyplot as plt
from scipy.stats import gaussian_kde
from sklearn.neighbors import KernelDensity
import os
from pathlib import Path
import pickle as pl

class Logger:
    def __init__(self, name: str, verbose: bool = False):
        """
        Initializes the logger.
        
        Parameters:
        name (str): Name of the logger, typically the class name or module name.
        verbose (bool): If True, set logging level to DEBUG, otherwise to WARNING.
        """
        self.logger = logging.getLogger(name)
        
        # Configure logging level based on verbosity
        if verbose:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.WARNING)
        
        # Prevent adding multiple handlers to the logger
        if not self.logger.hasHandlers():
            # Create console handler
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG)
            
            # Create formatter and add it to the handler
            formatter = logging.Formatter('%(name)s : %(levelname)s - %(message)s')
            ch.setFormatter(formatter)
            
            # Add handler to the logger
            self.logger.addHandler(ch)

    def log(self, message: str, level: str = 'info'):
        """
        Logs a message at the specified logging level.
        
        Parameters:
        message (str): The message to log.
        level (str): The logging level (debug, info, warning, error, critical).
        """
        level = level.lower()
        if level == 'debug':
            self.logger.debug(message)
        elif level == 'info':
            self.logger.info(message)
        elif level == 'warning':
            self.logger.warning(message)
        elif level == 'error':
            self.logger.error(message)
        elif level == 'critical':
            self.logger.critical(message)
        else:
            self.logger.info(message)


def inrad(alpha: float) -> float:
    """
    Converts an angle from degrees to radians.

    Parameters:
    alpha (float): The angle in degrees.

    Returns:
    float: The angle in radians.
    """
    return np.deg2rad(alpha)

def cli(cl: np.ndarray) -> np.ndarray:
    """
    Computes the inverse of each element in the input array `cl`.

    Parameters:
    cl (np.ndarray): Input array for which the inverse is calculated.
                     Only positive values will be inverted; zeros and negative values will remain zero.

    Returns:
    np.ndarray: An array where each element is the inverse of the corresponding element in `cl`,
                with zeros or negative values left unchanged.
    """
    ret = np.zeros_like(cl)
    ret[np.where(cl > 0)] = 1.0 / cl[np.where(cl > 0)]
    return ret


def download_file(url, filename):
    """Download a file with a progress bar."""
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    block_size = 1024 # 1 Kibibyte
    t = tqdm(total=total_size, unit='iB', unit_scale=True, desc=f'Downloading {filename}')
    with open(filename, 'wb') as file:
        for data in response.iter_content(block_size):
            t.update(len(data))
            file.write(data)
    t.close()


def deconvolveQU(QU,beam):
    """
    Deconvolves a beam from a QU map.

    Parameters:
    QU (np.ndarray): The input QU map.
    beam (np.ndarray): The beam to deconvolve.

    Returns:
    np.ndarray: The deconvolved QU map.
    """
    beam = np.radians(beam/60)
    nside = hp.npix2nside(len(QU[0]))
    elm,blm = hp.map2alm_spin(QU,2)
    lmax = hp.Alm.getlmax(len(elm))
    bl = hp.gauss_beam(beam,lmax=lmax,pol=True).T
    hp.almxfl(elm,cli(bl[1]),inplace=True)
    hp.almxfl(blm,cli(bl[2]),inplace=True)
    return hp.alm2map_spin([elm,blm],nside,2,lmax)


def change_coord(m, coord=['C', 'G']):
    npix = m.shape[-1]
    nside = hp.npix2nside(npix)
    ang = hp.pix2ang(nside, np.arange(npix))
    rot = hp.Rotator(coord=reversed(coord))
    new_ang = rot(*ang)
    new_pix = hp.ang2pix(nside, *new_ang)
    return m[..., new_pix]

def slice_alms(teb, lmax_new):
    """Returns the input teb alms sliced to the new lmax.

    teb(numpy array): input teb alms
    lmax_new(int): new lmax
    """
    s_arr = False
    if len(teb) > 3:
        s_arr = True
        teb = np.array([teb])
    lmax = hp.Alm.getlmax(len(teb[0]))
    if lmax_new > lmax:
        raise ValueError('lmax_new must be smaller or equal to lmax')
    elif lmax_new == lmax:
        return teb
    else:
        teb_new = np.zeros((len(teb), hp.Alm.getsize(lmax_new)), dtype=teb.dtype)
        indices_full = hp.Alm.getidx(lmax,*hp.Alm.getlm(lmax_new))
        indices_new = hp.Alm.getidx(lmax_new,*hp.Alm.getlm(lmax_new))
        teb_new[:,indices_new] = teb[:,indices_full]
        if s_arr:
            return teb_new[0]
        else:
            return teb_new
        
def bin_cmb_spectrum(arr, bin_width):
    """
    Bins a CMB power spectrum while avoiding the first two multipoles (l=0, l=1).

    Parameters:
    arr (numpy array): Input CMB power spectrum array.
    bin_width (int): The width of each bin.

    Returns:
    tuple: (binned_ells, binned_spectrum) where
           - binned_ells is an array of the central multipoles in each bin.
           - binned_spectrum is the averaged power spectrum in each bin.
    """
    lmax = len(arr) - 1  # Maximum multipole from the array length
    ells = np.arange(2, lmax + 1)  # Avoiding l=0, l=1

    binned_ells = []
    binned_spectrum = []

    for i in range(2, lmax + 1, bin_width):  # Start from l=2
        bin_range = np.arange(i, min(i + bin_width, lmax + 1))
        if len(bin_range) > 0:
            binned_ells.append(np.mean(bin_range))
            binned_spectrum.append(np.mean(arr[bin_range]))

    return np.array(binned_ells), np.array(binned_spectrum)



def plot_posterior(chains,
                   name=None,
                   labels=None,
                   colors=None,
                   fill_alpha=0.2,
                   sigma_line=True,
                   figsize=(6,6),
                   norm=True,
                   truth=None,
                   backend='scipy',
                   bandwidth=0.01,
    ):
    """
    Plots 1D posterior distributions for multiple chains using a KDE,
    with two separate legends:
      1) One for the KDE lines
      2) One for the 1σ (16th–84th) shaded regions (showing std in scientific notation)
    
    Parameters
    ----------
    chains : list of np.ndarray
        Each element is a 1D array of MCMC samples for the same parameter.
    name : str, optional
        Label for the x-axis (parameter name).
    labels : list of str, optional
        Labels for each chain in the first legend.
    colors : list of str, optional
        Colors for each chain. Defaults to matplotlib cycle if None.
    fill_alpha : float, optional
        Transparency of the 1σ shading.
    sigma_line : bool, optional
        If True, draws vertical dashed lines at p16 and p84.
    figsize : tuple, optional
        (width, height) for the figure in inches.
    norm : bool, optional
        If True, normalize each chain's KDE peak to 1.
        If False, use original KDE scale.
    truth : float, optional
        If provided, a vertical dashed line is drawn at this x-value.
    backend : {'scipy', 'sklearn'}, optional
        Backend for KDE. 
        - 'scipy': uses scipy.stats.gaussian_kde
        - 'sklearn': uses sklearn.neighbors.KernelDensity
    bandwidth : float, optional
        Bandwidth for the KDE. 
        - For 'scipy', it’s passed as `bw_method`.
        - For 'sklearn', it’s passed as `bandwidth` in KernelDensity.
        If None, the default method is used.
    """
    n_chains = len(chains)
    
    # Default labels if not provided
    if labels is None:
        labels = [f"Chain {i+1}" for i in range(n_chains)]

    # Default colors if not provided
    if colors is None:
        colors = [f"C{i}" for i in range(n_chains)]
    
    # Set up figure
    plt.figure(figsize=figsize)

    # Determine a common x-range
    all_samples = np.concatenate(chains)
    x_min, x_max = np.min(all_samples), np.max(all_samples)
    x_vals = np.linspace(x_min, x_max, 500)

    # Lists to store line/fill handles for the legends
    line_handles = []
    line_labels = []
    fill_handles = []
    fill_labels = []

    for i, samples in enumerate(chains):
        # Compute the 16th and 84th percentile, as well as std dev
        p16, p84 = np.percentile(samples, [16, 84])
        std_val = np.std(samples)

        # ------------------------
        # Build the KDE
        # ------------------------
        if backend == 'scipy':
            # Using scipy.stats.gaussian_kde
            if bandwidth is not None:
                # bw_method can be a scalar or a string. If scalar, factor is 
                # multiplied by scotts_factor or silverman_factor.
                kde = gaussian_kde(samples, bw_method=bandwidth)
            else:
                # Default bandwidth selection
                kde = gaussian_kde(samples)
            
            # Evaluate the KDE on x_vals
            pdf_vals = kde(x_vals)
            
            # Evaluate exactly at p16 & p84
            pdf_p16 = kde([p16])[0]
            pdf_p84 = kde([p84])[0]
        
        elif backend == 'sklearn':
            # Using sklearn.neighbors.KernelDensity
            samples_2d = samples.reshape(-1, 1)
            
            if bandwidth is not None:
                kde = KernelDensity(kernel='gaussian', bandwidth=bandwidth)
            else:
                # If no bandwidth supplied, let sklearn pick default=1.0
                kde = KernelDensity(kernel='gaussian')
            
            # Fit the model
            kde.fit(samples_2d)
            
            # Evaluate on the grid
            log_pdf_vals = kde.score_samples(x_vals.reshape(-1,1))
            pdf_vals = np.exp(log_pdf_vals)
            
            # Evaluate at p16 and p84
            log_pdf_p16 = kde.score_samples(np.array([[p16]]))
            log_pdf_p84 = kde.score_samples(np.array([[p84]]))
            pdf_p16 = np.exp(log_pdf_p16)[0]
            pdf_p84 = np.exp(log_pdf_p84)[0]
        
        else:
            raise ValueError(f"Invalid backend: {backend}. Choose 'scipy' or 'sklearn'.")

        # ------------------------
        # Optional normalization (peak -> 1)
        # ------------------------
        if norm:
            peak = np.max(pdf_vals)
            pdf_vals /= peak
            pdf_p16 /= peak
            pdf_p84 /= peak

        # ------------------------
        # Plot the main KDE line
        # ------------------------
        (line,) = plt.plot(
            x_vals, pdf_vals,
            color=colors[i]
        )
        line_handles.append(line)
        line_labels.append(labels[i])

        # ------------------------
        # Fill the 1σ region
        # ------------------------
        # We'll label this region with the standard deviation in scientific notation
        fill_label = f"{std_val:.2e}"
        fill = plt.fill_between(
            x_vals, pdf_vals,
            where=(x_vals >= p16) & (x_vals <= p84),
            color=colors[i],
            alpha=fill_alpha
        )
        fill_handles.append(fill)
        fill_labels.append(fill_label)

        # ------------------------
        # Optionally draw vertical lines at p16 & p84
        # ------------------------
        if sigma_line:
            plt.vlines(
                x=p16,
                ymin=0,
                ymax=pdf_p16,
                color=colors[i],
                ls='--',
                alpha=0.5
            )
            plt.vlines(
                x=p84,
                ymin=0,
                ymax=pdf_p84,
                color=colors[i],
                ls='--',
                alpha=0.5
            )

    # ------------------------
    # Optional truth line
    # ------------------------
    if truth is not None:
        plt.axvline(truth, color='k', ls='--')

    # Set axes labels
    plt.xlabel(name if name else "Parameter Value")
    plt.ylabel("Normalized PDF" if norm else "PDF")

    # ------------------------
    # Two separate legends
    # ------------------------
    legend1 = plt.legend(
        handles=line_handles,
        labels=line_labels,
        title="Samples",
        loc="upper left"
    )
    plt.gca().add_artist(legend1)

    legend2 = plt.legend(
        handles=fill_handles,
        labels=fill_labels,
        title="1$\sigma$ Intervals",
        loc="upper right"
    )
    
    plt.ylim(0.01, 1.3)
    plt.tight_layout()
    plt.show()


def get_n0_qe(nlev_p):
    fname = (Path(__file__).resolve().parent.parent / 'data'/'n0_iter.pkl')
    if not fname.exists():
        raise FileNotFoundError(f"File {fname} not found")
    return pl.load(open(fname,'rb'))[nlev_p][0]

def get_n0_iter(nlev_p):
    fname = (Path(__file__).resolve().parent.parent / 'data'/'n0_iter.pkl')
    if not fname.exists():
        raise FileNotFoundError(f"File {fname} not found")
    return pl.load(open(fname,'rb'))[nlev_p][1]

