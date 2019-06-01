import pandas as pd
import os
import numpy as np
import json
import glob
import sys
import time

from git import Repo


def find_range(x,a,b,option='within'):
    
    """
    Find indices of data within or outside range [a,b]

    Inputs:
    -------
    x - numpy.ndarray
        Data to search
    a - float or int
        Minimum value
    b - float or int
        Maximum value
    option - String
        'within' or 'outside'

    Output:
    -------
    inds - numpy.ndarray
        Indices of x that fall within or outside specified range

    """

    if option=='within':
        return np.where(np.logical_and(x>=a, x<=b))[0]
    elif option=='outside':
        return np.where(np.logical_or(x < a, x > b))[0]
    else:
        raise ValueError('unrecognized option paramter: {}'.format(option))


def rms(data):

    """
    Computes root-mean-squared voltage of a signal

    Input:
    -----
    data - numpy.ndarray

    Output:
    ------
    rms_value - float
    
    """

    return np.power(np.mean(np.power(data.astype('float32'),2)),0.5)

def write_probe_json(output_file, channels, offset, scaling, mask, surface_channel, air_channel, vertical_pos, horizontal_pos):

    """
    Writes a json file containing information about one Neuropixels probe.

    Inputs:
    -------
    output_file : file path
        Location for writing the json file
    channels : numpy.ndarray (384 x 0)
        Probe channel numbers
    offset : numpy.ndarray (384 x 0)
        Offset of each channel from zero
    scaling : numpy.ndarray (384 x 0)
        Relative noise level on each channel
    mask : numpy.ndarray (384 x 0)
        1 if channel contains valid data, 0 otherwise
    surface_channel : Int
        Index of channel at brain surface
    air_channel : Int
        Index of channel at interface between saline/agar and air
    vertical_pos : numpy.ndarray (384 x 0)
        Distance (in microns) of each channel from the probe tip
    horizontal_pos : numpy.ndarray (384 x 0)
        Distance (in microns) of each channel from the probe edge

    Outputs:
    --------
    output_file.json (written to disk)

    """

    with open(output_file, 'w') as outfile:
        json.dump( 
                  {  
                        'channel' : channels.tolist(), 
                        'offset' : offset.tolist(), 
                        'scaling' : scaling.tolist(), 
                        'mask' : mask.tolist(), 
                        'surface_channel' : surface_channel, 
                        'air_channel' : air_channel,
                        'vertical_pos' : vertical_pos.tolist(),
                        'horizontal_pos' : horizontal_pos.tolist()
                   },
                 
                  outfile, 
                  indent = 4, separators = (',', ': ') 
                 ) 

def read_probe_json(input_file):

    """
    Reads a json file containing information about one Neuropixels probe.

    Inputs:
    -------
    input_file : file path
        Location of file to read

    Outputs:
    --------
    mask : numpy.ndarray (384 x 0)
        1 if channel contains valid data, 0 otherwise
    offset : numpy.ndarray (384 x 0)
        Offset of each channel from zero
    scaling : numpy.ndarray (384 x 0)
        Relative noise level on each channel
    surface_channel : Int
        Index of channel at brain surface
    air_channel : Int
        Index of channel at interface between saline/agar and air

    """
    
    with open(input_file) as data_file:
        data = json.load(data_file)
    
    scaling = np.array(data['scaling'])
    mask = np.array(data['mask'])
    offset = np.array(data['offset'])
    surface_channel = data['surface_channel']
    air_channel = data['air_channel']

    return mask, offset, scaling, surface_channel, air_channel


def write_cluster_group_tsv(IDs, quality, output_directory):

    cluster_quality = []
    cluster_index = []
    
    for idx, ID in enumerate(IDs):
        
        cluster_index.append(ID)
        
        if quality[idx] == 0:
            cluster_quality.append('unsorted')
        elif quality[idx] == 1:
            cluster_quality.append('good')
        else:
            cluster_quality.append('noise')
       
    df = pd.DataFrame(data={'cluster_id' : cluster_index, 'group': cluster_quality})
    
    print('Saving data...')
    
    df.to_csv(os.path.join(output_directory, 'cluster_group.tsv'), sep='\t', index=False)


def read_cluster_group_tsv(filename):

    info = np.genfromtxt(filename, dtype='str')
    cluster_ids = info[1:,0].astype('int')
    cluster_quality = info[1:,1]

    return cluster_ids, cluster_quality

def load(folder, filename):

    return np.load(os.path.join(folder, filename))

def load_kilosort_data(folder, sample_rate, convert_to_seconds = True, use_master_clock = False, include_pcs = False, template_zero_padding= 21):

    if use_master_clock:
        spike_times = load(folder,'spike_times_master_clock.npy')
    else:
        spike_times = load(folder,'spike_times.npy')
        
    spike_clusters = load(folder,'spike_clusters.npy')
    amplitudes = load(folder,'amplitudes.npy')
    templates = load(folder,'templates.npy')
    unwhitening_mat = load(folder,'whitening_mat_inv.npy')
    channel_map = load(folder, 'channel_map.npy')

    if include_pcs:
        pc_features = load(folder, 'pc_features.npy')
        pc_feature_ind = load(folder, 'pc_feature_ind.npy')
                
    templates = templates[:,template_zero_padding:,:] # remove zeros
    spike_clusters = np.squeeze(spike_clusters) # fix dimensions
    spike_times = np.squeeze(spike_times)# fix dimensions
    if convert_to_seconds:
       spike_times = spike_times / sample_rate # convert to seconds
                    
    unwhitened_temps = np.zeros((templates.shape))
    
    for temp_idx in range(templates.shape[0]):
        
        unwhitened_temps[temp_idx,:,:] = np.dot(np.ascontiguousarray(templates[temp_idx,:,:]),np.ascontiguousarray(unwhitening_mat))
                    
    try:
        cluster_ids, cluster_quality = read_cluster_group_tsv(os.path.join(folder, 'cluster_group.tsv'))
    except OSError:
        cluster_ids = np.unique(spike_clusters)
        cluster_quality = ['unsorted'] * cluster_ids.size

    if not include_pcs:
        return spike_times, spike_clusters, amplitudes, unwhitened_temps, channel_map, cluster_ids, cluster_quality
    else:
        return spike_times, spike_clusters, amplitudes, unwhitened_temps, channel_map, cluster_ids, cluster_quality, pc_features, pc_feature_ind


def get_repo_commit_date_and_hash(repo_location):

    """
    Finds the date and hash of the latest commit in a git repository

    Input:
    ------
    repo_location - String
        Local directory containing the git repository

    Outputs:
    --------
    commit_date - String
        Date string of the latest commit
    commit_hash - String
        Hash of the latest commit

    """

    if os.path.exists(repo_location):
        repo = Repo(repo_location)
        headcommit = repo.head.commit
        commit_date = time.strftime("%a, %d %b %Y %H:%M", time.gmtime(headcommit.committed_date))
        commit_hash = headcommit.hexsha
    else:
        commit_date = 'none'
        commit_hash = 'none'

    return commit_date, commit_hash


def printProgressBar(iteration, total, prefix = '', suffix = '', decimals = 0, length = 40, fill = '▒'):
    
    """
    Call in a loop to create terminal progress bar

    Code from https://stackoverflow.com/questions/3173320/text-progress-bar-in-the-console

    Inputs:
    -------
    iteration - Int
        Current iteration
    total - Int
        Total iterations
    prefix - Str (optional)
        Prefix string
    suffix - Str (optional)
        Suffix string
    decimals - Int (optional)
        Positive number of decimals in percent complete
    length - Int (optional)
        Character length of bar
    fill - Str (optional)
        Bar fill character

    Outputs:
    --------
    None
    
    """
    
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filledLength = int(length * iteration // total)
    bar = fill * filledLength + '░' * (length - filledLength)
    sys.stdout.write('\r%s %s %s%% %s' % (prefix, bar, percent, suffix))
    sys.stdout.flush()

    if iteration == total: 
        print()