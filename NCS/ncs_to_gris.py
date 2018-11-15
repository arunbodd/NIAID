#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Sep  5 10:43:58 2018
Updated on

Susan Huse
NIAID Center for Biological Research
Frederick National Laboratory for Cancer Research
Leidos Biomedical

ncs_to_gris.py
    Reads the sample mapping and VCF information and 
    preps the metadata for uploading to GRIS

v 1.0 - initial code version.

Quality Checks:
    *  which individuals have been returned in this batch
    *  each individual belongs to only one family
    *  family IDs based on Phenotips and MRNs map one-to-one
    *  Order IDs are consistent between pedigree, sample mapping, sample key and orders sent
    *  Finds and removes the duplicate and the control entries
    
"""
__author__ = 'Susan Huse'
__date__ = 'September 5, 2018'
__version__ = '1.0'
__copyright__ = 'No copyright protection, can be used freely'

import sys
import os
import re
import datetime
import pandas as pd
import numpy as np
from yaml import load
import argparse
from argparse import RawTextHelpFormatter
from ncbr_huse import send_update, err_out, pause_for_input
#from ncbr_huse import run_cmd, run_os_cmd, un_gzip, send_update, err_out
#import csv
#import scipy
#import numpy

 
####################################
# 
# Functions for processing data
#
####################################
# Test file exists or error out
def test_file(f):
    if not os.path.isfile(f):
        err_out("Error: unable to locate input file:  " + f, log)
    else:
        return(True)

# Compare indices of two data series, return missing values
def compare_keys(x,y):
    # join outer, so missing values with be null values in the x or y column
    print("X:\n{}".format(x.head()))
    print("Y:\n{}".format(y.head()))
    xy = pd.concat([x,y], axis=1, join='outer', sort=False)

    # search for the null values by column, return the index value
    missing_in_x = xy.loc[xy.iloc[:,0].isnull()].index.values
    missing_in_y = xy.loc[xy.iloc[:,1].isnull()].index.values

    return(missing_in_x, missing_in_y)


# Create the prompt to be used by get_bsi_data
def bsi_prompt_text(bsifile, idname, reccnt):
    return('\n'.join(["", stars, stars, "Please log into BSI and create a new report that includes:",
    "Subject ID", "PhenotipsId", "CRIS Order #", "Phenotips Family ID", "Batch Sent\n",
    "Use the following {}s as search criteria ({} =@(like) *inserted IDs*).".format(idname, idname),
    'Run the report and save the file as: "{}" in the same directory as {}'.format(bsifile, config['config_fname']),
    '\nPlease enter "y" to print out the list of {} {}s to use, or "q" to quit.\n'.format(reccnt, idname)]))

# Get the Phenotips information for the subjects in this batch and previous batches
def get_bsi_data(f1, f2, mrns, added, dropped):

    # Prompt and import the first set of BSI data - subjects released in this batch
    if not testmode:
        pause_for_input(bsi_prompt_text(f1, "Subject ID", str(len(mrns))), 'y', 'q', log)
        print("\n" + "\n".join(mrns))
        pause_for_input('\nPlease enter "y" to continue when you have created {}, or "q" to quit.\n'.format(f1), 'y','q', log)

    bsi1 = import_bsi_phenotips(f1)
    #print("BSI1:\n{}".format(bsi1.head()))
    
    # Prompt and import the first set of BSI data - subjects released in previous batches
    if not testmode:
        added = pd.DataFrame(added)
        dropped = pd.DataFrame(dropped)
        both = pd.concat([pd.DataFrame(added), pd.DataFrame(dropped)])
        pause_for_input(bsi_prompt_text(f2, "CRIS Order #", str(len(both))), 'y', 'q', log)
        print("\n" + "\n".join(both.iloc[:,0]))
        pause_for_input('\nPlease enter "y" to continue when you have created this file, {}, or "q" to quit.\n'.format(f2), 'y','q', log)

    bsi2 = import_bsi_phenotips(f2)
    #print("BSI2:\n{}".format(bsi2.head()))
    
    bsi = pd.concat([bsi1,bsi2], sort=True)
    bsi.drop_duplicates(inplace=True)
    bsi = bsi.set_index(['Subject_ID'])
    #print("BSI:\n{}".format(bsi.head()))
    return(bsi)

# Create the prompt to be used by get_bsi_exomes
def bsi_exomes_prompt_text(bsifile, idname, reccnt):
    return('\n'.join(["", stars, stars, "Please log into BSI and create a new report that includes:",
    "CRIS Order #", "CIDR Exome ID", "Batch Received\n",
    "Use the following {}s as search criteria ({} =@(like) *inserted IDs*).".format(idname, idname),
    'Run the report and save the file as: "{}" in the same directory as {}'.format(bsifile, config['config_fname']),
    '\nPlease enter "y" to print out the list of {} {}s to use, or "q" to quit.\n'.format(reccnt, idname)]))

# Get the CIDR_Exome_ID information for the subjects missing exome IDs
def get_bsi_exomes(f3, ids):
    # Prompt and import the set of missing data 
    if not testmode:
        pause_for_input(bsi_exomes_prompt_text(f3, "CRIS Order #", str(len(ids))), 'y', 'q', log)
        print("\n" + "\n".join(ids))
        pause_for_input('\nPlease enter "y" to continue when you have created {}, or "q" to quit.\n'.format(f3), 'y','q', log)

    bsi = import_bsi_exomes(f3)
    bsi = bsi.set_index(['Subject_ID'])

    return(bsi)

######################################
#   
# Functions for importing data
#
######################################

# Find the duplicate ID from the pedigree file
def find_the_duplicate(df, fformat):
    if fformat == "ped":
        # find the duplicate using the comments column with the word "duplicate"
        dupestr = df[df['Investigator Column 1'].str.contains('Duplicate', case=False, na=False)]['Subject_ID']
        # find the duplicate because it is the only subject ID > 9 characters
        dupelen = df.loc[df['Subject_ID'].str.len() > 9]['Subject_ID']
        # If the two methods aren't the same answer, error out
        if not dupestr.equals(dupelen):
            err_out("Warning: unable to ascertain duplicate sample identifier.\n" + \
                    "{} was identified in the pedigree file as a duplicate in 'Investigator Column 1',\n" + \
                    "{} has Subject_ID length > 9 characters.\n" + \
                    "Exiting".format(dupestr, dupelen), log)

    elif fformat == "manifest":
        # find the duplicate because it is the only subject ID > 9 characters
        dupestr = df.loc[(df['Subject_ID'].str.len() > 9) & (df['Subject_ID'] != "CONTROL_ID")]['Subject_ID']

    if dupestr.size > 1:
        send_update("Warning: found more than one duplicate sample identifier: {}.".format(dupestr.tolist()), log)
    elif dupestr.size < 1:
        send_update("Warning: no duplicate sample identifier was found in the {} file.".format(fformat), log)
        return(None)

    send_update("Duplicate sample identifier: {}".format(dupestr), log)

    return(dupestr.tolist())

# Find the control ID from the 
def find_the_control(x):
    
    # search the indices for anything with NA or with HG
    regexNA = re.compile('^NA')
    regexHG = re.compile('^HG')
    ctrl = [i for i in x.index.tolist() if regexNA.match(i)]
    ctrlHG = [i for i in x.index.tolist() if regexHG.match(i)]
    ctrl.extend(ctrlHG)

    if len(ctrl) != 1:
        error_text = "\nError: found {} control sample identifier(s), expected only one.\n{}".format(str(len(ctrl))    ,ctrl) 
        error_text = error_text + '\nPlease enter "y" to continue or "q" to quit.\n'
        pause_for_input(error_text, 'y', 'q', log)

    send_update("Control sample identifier: {}".format(ctrl[0]), log)
    return(ctrl[0])

# Import pedigree information from Excel file
def import_pedigree(f):
    test_file(f)
    
    # import the data
    # but some are csv and some are excel! 
    if bool(re.search('.csv$', f)):
        ped = pd.read_csv(f)
    elif bool(re.search('.xlsx*$', f)):
        ped = pd.read_excel(f)
    else:
        err_out("Error: Confused by pedigree file name {}, expecting *.csv or *.xlsx.\nExiting.".format(f), log)
        
    ## Each set has a sequencing duplicate that should be removed
    theDupe = find_the_duplicate(ped, "ped")

    # create a series of batch information with Subject as the index
    batches = ped[ped['Subject_ID'] != ""][['Subject_ID', 'Investigator Column 3']]
    batches = batches[batches.Subject_ID.notnull()].set_index('Subject_ID')
    batches = batches['Investigator Column 3'].str.replace("_.*$", "", regex=True)

    if theDupe != None:
        batches = batches.drop([theDupe])

    return(batches, theDupe)

# Import sample mapping information from csv file
def import_samplemapping(f, dup, findControl):
    test_file(f)

    # import and create series with index
    mapping = pd.read_csv(f, header=0)
    mapping = mapping.set_index('SUBJECT_ID')['SAMPLE_ID']

    # find the Control, and then remove it and the dupe
    # Will read old ones too and you don't want to change the control
    if(findControl):
        ctrl = find_the_control(mapping)
        mapping = mapping.drop([ctrl])
    else:
        ctrl=None

    if dup != None:
        mapping = mapping.drop([dup])

    return(mapping, ctrl)

# Import sample key information from csv file
def import_samplekey(f, dupe, ctrl):
    test_file(f)

    # import and convert to series
    samplekey = pd.read_csv(f, header=0)
    samplekey = samplekey.set_index('Subject_ID')
    samplekey = samplekey['LIMS_SampleId']

    # remove the duplicate and control
    samplekey = samplekey.drop([dupe, ctrl])

    return(samplekey)

# Import orders information from csv file
def import_orders(f):
    test_file(f)

    # import and convert MRN to series
    orders = pd.read_csv(f, header=2, sep=',')

    # remove sapces if necessary, grab out Subject ID = MRN, and CRIS Order # = new Subject_ID
    #orders.columns = orders.columns.map(str)
    orders.columns = [x.strip() for x in orders.columns]
    orders = orders.loc[:, ['Subject ID','CRIS Order #']]
    # remap column names Subject_ID to MRN, and CRIS Order # to Subject ID
    orders.columns.values[0] = "MRN"
    orders.columns.values[1] = "Subject_ID"
    # Set SubjectID to index and remove as a column.
    orders.set_index('Subject_ID', inplace=True)
    orders = orders['MRN']
    # no duplicates or controls in this

    return(orders)

# Import manifest information from csv file
def import_manifest(f, dupe):
    test_file(f)

    # import and convert to dataframe
    manifest = pd.read_excel(f, usecols=[1,2], header=4)
    manifest = pd.DataFrame(data=manifest, dtype='str')
    manifest.columns.values[1] = "Subject_ID"
    manifest.columns.values[0] = "Well"

    ## Each set has a sequencing duplicate that should be removed
    if dupe == None:
        dupe = find_the_duplicate(manifest, "manifest")

    # remove nulls, control_id values, and the duplicate
    manifest = manifest[manifest['Subject_ID'] != "CONTROL_ID"]
    if dupe != None:
        #manifest = manifest[manifest['Subject_ID'] != dupe]
        manifest = manifest[~manifest.Subject_ID.isin(dupe)]
    manifest.dropna(subset=['Subject_ID'], inplace=True) # read_excel is not using null, but "nan"
    manifest = manifest[manifest['Subject_ID'] != "nan"] # not actually null, "nan" string

    # convert to indexed series
    manifest.set_index('Subject_ID', inplace=True)
    manifest = manifest['Well']

    return(manifest)

# Import the full pedigree with family info for all subjects
def import_fullpedigree(f):
    test_file(f)

    # import and convert to dataframe, use MRN as index to find the family
    fullped = pd.read_csv(f, header=0, sep='\t')
    fullped = fullped.iloc[:,0:9]
    colnames = ['Family_ID', 'MRN', 'Proband', 'Father', 'Mother', 'Gender', 'Affected', 'Recorder', 'Batch']
    fullped.set_axis(colnames, axis=1, inplace=True)
    fullped.set_index('MRN', inplace=True)

    return(fullped)

# Import the BSI phenotips information
def import_bsi_phenotips(f):
    test_file(f)

    # import and convert to dataframe, using field names
    phenotips = pd.read_csv(f, header=2)

    # Test that all necessary columns are there
    theCols = phenotips.columns
    missing = []

    for c in ['Subject ID', 'PhenotipsId', 'CRIS Order #', 'Phenotips Family ID', 'Batch Sent']:
        if c not in theCols:
            missing.append(c)

    if len(missing) > 0:
        err_out("Phenotips CSV file exported from BSI is missing required field(s):\n{}".format("\n".join(missing)), log)
    
    # rename the columns
    phenotips = phenotips.rename(columns = {'Subject ID':'MRN', 
                                            'PhenotipsId':'Phenotips_ID', 
                                            'Phenotips Family ID': 'Phenotips_Family_ID',
                                            'CRIS Order #':'Subject_ID', 
                                            'Batch Sent':'Batch_Sent'})
    
    # drop the row count column
    phenotips = phenotips.drop(columns=['OBS'])

    return(phenotips)
    
# Import the BSI CIDR Exome ID information
def import_bsi_exomes(f):
    test_file(f)

    # import and convert to dataframe, using field names
    exomes = pd.read_csv(f, header=2)

    # Test that all necessary columns are there
    theCols = exomes.columns
    missing = []

    for c in ['CRIS Order #', 'CIDR Exome ID', 'Batch Received']:
        if c not in theCols:
            missing.append(c)

    if len(missing) > 0:
        err_out("CIDR Exome ID CSV file (bsi3.csv) exported from BSI is missing required field(s):\n{}".format("\n".join(missing)), log)
    
    # rename the columns
    exomes = exomes.rename(columns = {'CRIS Order #':'Subject_ID', 
                                            'CIDR Exome ID':'CIDR_Exome_ID',
                                            'Batch Received':'Batch_Received'})
    
    # drop the row count column
    exomes = exomes.drop(columns=['OBS'])

    return(exomes)
    
######################################
#   
# Functions for writing output files
#
######################################

# Print out batch information to the readme file
def write_batch_info(added_to_batch, dropped_from_batch, batches, masterdf, f, append=False):
    #print("MasterDF:\n{}".format(masterdf.head()))
    #print("Batches:\n{}".format(batches.head()))
    #print("Added to Batch:\n{}".format(added_to_batch))
    #print("Batch Info for Adds:\n{}".format(batches.loc[added_to_batch]))
    
    # Header
    headText = "\n".join(["", stars, "*", "* Notes for samples released with Batch {}", "*", stars]).format(str(batch))

    # Total number released
    bodyText = "Total number of samples released in Batch {}: {}\n".format(str(batch), str(batches.size))

    # Number released in this batch that were sent with this batch
    inThisBatch = batches.size - len(added_to_batch)
    thisBatchText = "{} samples that were sent to CIDR in Batch {} were released with Batch {}.".format(str(inThisBatch), str(batch), str(batch))

    sampleCols = ['Phenotips_ID', 'Phenotips_Family_ID']
    # Samples that have not yet been released
    #print("MasterDF:\n{}".format(masterdf.head()))
    missingDF = masterdf.loc[dropped_from_batch]
    missingDF = missingDF[sampleCols]
    missingText = "\n{} sample(s) sent to CIDR in Batch {} have not yet been released".format(str(len(dropped_from_batch)), str(batch))
    if missingDF.shape[0] > 0:
        missingText = missingText + ":\nOrder{}\n".format(missingDF.to_string(justify='left'))
    else:
        missingText = missingText + ".\n"

    # Samples from earlier batches that were released with this batch
    #df = pd.concat([bsi, mapping], axis=1, join='outer', sort=False)
    added_batches = pd.concat([ masterdf.loc[added_to_batch][['Phenotips_ID', 'Phenotips_Family_ID', 'Batch']],
                    batches.loc[added_to_batch]], axis=1, join='outer', sort=False)
    added_batches = added_batches.iloc[:, [0,1,3]]
    added_batches.columns = ['Phenotips_ID', 'Phenotips_Family_ID', 'Batch']

    # Get the other data for added, then set the batch number
    addedText = "{} sample(s) sent to CIDR in earlier batches were released with Batch {}".format(str(len(added_to_batch)), \
               str(batch))
    if len(added_to_batch) > 0:
        #addedText = addedText + ":\nOrder{}".format(addedDF.to_string(columns=['Phenotips_ID', 'Phenotips_Family_ID', 'Batch'], justify='left'))
        addedText = addedText + ":\nOrder{}".format(added_batches, justify='left')
    else:
        addedText = addedText + ".\n"

    # Join the text and write it out to both the log and the README file
    theText = "\n".join([headText, bodyText, thisBatchText,  missingText, addedText]) + "\n"
    send_update(theText, log)
    send_update(theText, f, True)

    return(added_batches)

# Write out information on the number of families, and those that are split across batches
def write_family_info(newpedDF, batches, fams, mrns, f):
    family_count = len(newpedDF['Phenotips_Family_ID'].unique())
     
    # Count of families and patients in those families
    bodyText = "The {} patients released in Batch {} belong to {} unique families.\n".format(str(batches.size), str(batch), str(family_count))
    bodyText = bodyText + "The {} families include {} total patients.".format(str(family_count), str(len(mrns)))

    send_update(bodyText, log)
    send_update(bodyText, f, True)

    return(True)

# Check the family names are okay
def check_family_ids(df):# (a, p):
    df = df[['Family_ID', 'Phenotips_Family_ID']]
    # This line causes Warning flag:
    #/Users/husesm/bin/ncs_to_gris.py:424: SettingWithCopyWarning: 
    # A value is trying to be set on a copy of a slice from a DataFrame
    #See the caveats in the documentation: http://pandas.pydata.org/pandas-docs/stable/indexing.html#indexing-view-versus-copy
    #  df.drop_duplicates(subset = ['Family_ID', 'Phenotips_Family_ID'], inplace=True)
    #  FC: 67, 67, 67
    #  {67}

    df.drop_duplicates(subset = ['Family_ID', 'Phenotips_Family_ID'], inplace=True)

    rowcnt = df.shape[0]
    mf = len(set(df['Family_ID']))
    pf = len(set(df['Phenotips_Family_ID']))
    print("FC: {}, {}, {}".format(str(rowcnt), str(mf), str(pf)))
    print(set([rowcnt, mf, pf]))

    if len(set([rowcnt, mf, pf])) > 1:
        err_out("Family IDs from Batch {} pedigree file ({}) do not consistently match the Phenotips Family IDs.\n" + \
                 "Please review the Family IDs and correct as appropriate.\n{}\n" +\
                 "Exiting...".format(batch, config['pedigree'], df), log)
    else:
        send_update("Family IDs from Batch {} pedigree files and the Phenotips Family IDs match one to one\n".format(batch), log)
        return(True)

def create_master_df(bsi, mapping, ped):
    #print("PED:\n{}".format(ped.to_string()))
    #print("BSI:\n{}".format(bsi.head()))
    #print("Mapping:\n{}".format(mapping.head()))
    # Combine the BSI information and the original mapping info
    df = pd.concat([bsi, mapping], axis=1, join='outer', sort=False)
    df['Subject_ID'] = df.index
    df = df.rename(columns = {'SAMPLE_ID':'CIDR_Exome_ID'})
    df = df.dropna(subset=['Batch_Sent'])

    # Subset the ped file and merge it in
    #print("DF MRN:\n{}".format(list(df['MRN'])))
    # this line causes FutureWarning:
    #/Users/husesm/bin/ncs_to_gris.py:453: FutureWarning: 
    #Passing list-likes to .loc or [] with any missing label will raise
    #KeyError in the future, you can use .reindex() as an alternative.

    #See the documentation here:
    #https://pandas.pydata.org/pandas-docs/stable/indexing.html#deprecate-loc-reindex-listlike
    # ped = ped.loc[df['MRN']]

    ped = ped.loc[df['MRN']]
    df = pd.merge(ped, df, how='outer', left_index=True, right_on='MRN')
    df.drop_duplicates(inplace=True)

    #print("MasterDF:\n{}".format(df.head()))
    return(df)

# Write out the master key for selecting all current and past family VCF data
def write_keys(df, mrns, notinbatch, ped, bsidf, fmasterkey, fmrn, readmef):
    #print("Ped:\n{}".format(ped.head()))

    df = df[['MRN', 'Subject_ID', 'Phenotips_ID', 'Phenotips_Family_ID', 'CIDR_Exome_ID', 'Batch']]
    #print("DF:\n{}".format(df.head()))

    # Exome IDs for family members that were released in earlier batches
    missing = df[df['CIDR_Exome_ID'].isnull()].index
    #print("All Missing:\n{}".format(missing))
    
    # for all the missing ones, remove the ones that were sent with this batch but not received
    for i in missing:
        if i in notinbatch:
            missing.remove(i)
    #print("Missing family not from current batch:\n{}".format(missing))

    #send_update("Full list of missing family member order numbers:\n{}".format(missing.values.tolist()), log)
    send_update("There are {} family members identified in BSI with CIDR Exome IDs that were not sent with this batch.\n".format(missing.size), log)
    family_members = get_bsi_exomes(config['bsi3'], missing.values.tolist())
    #print("Family Members:\n{}".format(family_members))

    # Drop records without Batch Received or Exome ID
    # Create a numeric batch number for comparison, and only keep records older than current batch
    family_members = family_members.dropna()
    family_members = family_members[family_members.Batch_Received.str.contains("batch", case=False)]
    family_members['Batch_Number'] = family_members['Batch_Received'].str.replace("BATCH0*", "")
    family_members['Batch_Number'] = pd.to_numeric(family_members['Batch_Number'])
    family_members = family_members[family_members['Batch_Number'] < int(batch)]

    # Insert the found exome IDs 
    df.loc[family_members.index,'CIDR_Exome_ID'] = family_members['CIDR_Exome_ID']

    # remove extraneous data that came back from BSI, multiple orders of same person
    df = df[df['CIDR_Exome_ID'].notnull()]

    # Add missing not found
    stillmissing = set(missing) - set(family_members.index.values)
    #print("Still Missing:\n{}".format(stillmissing))

    # Fill in any missing batch information
    lostbatch_idx = df[df['Batch'].isnull()].index
    lostbatch_idx = [i.replace('\n','') for i in lostbatch_idx]
    lostbatch = bsidf.loc[lostbatch_idx][['Batch_Sent']]
    df = pd.concat([df,lostbatch], axis=1, join='outer', sort=False)
    df['Batch'] = np.where(df['Batch'].isnull(), df['Batch_Sent'], df['Batch'])
    df = df.drop(['Batch_Sent'], axis=1)

    # For dropped MRNs, get the Phenotips ID and export
    droppedMRNs = set(mrns) - set(df['MRN'])
    droppedPIDs = bsidf.loc[bsidf['MRN'].isin(droppedMRNs)][['Phenotips_ID', 'Phenotips_Family_ID']].reset_index()
    droppedPIDs.columns = ['CRIS Order #', 'Phenotips_ID', 'Phenotips_Family_ID']
    
    ## Add the text for the Found individuals
    updateText = "Samples for {} individual(s) matching families released with Batch {} were released in previous batches.\n".format(str(family_members.shape[0]), batch)
    if family_members.shape[0] > 0:
        updateText = updateText + "{}\n\n".format(family_members.iloc[:,0:2])

    ## Add the text for those still missing, but remove dupes
    if len(droppedMRNs) + len(stillmissing) > 0:
        # print out the droppedPIDs data frame and any other missing order numbers
        updateText = updateText + "Sequencing data for {} individual(s) matching families in Batch {} are not yet available.\n{}\n{}\n\n".format(str(len(stillmissing) + len(droppedMRNs)), batch, droppedPIDs.to_string(index=False), "  "+"\n  ".join(stillmissing - set(droppedPIDs['CRIS Order #'])))
    else:
        updateText = updateText + "\nSequencing for all family members has been released.\n"

    # Check that all the MRNs are accounted for, update log and README
    updateText = updateText + "Data for {} individuals will be uploaded to GRIS with Batch {},".format(str(len(set(df['MRN']))), str(batch))

    send_update(updateText, log)
    send_update(updateText, readmef, True)

    #print("DF to VCF:\n{}".format(df.head()))
    # Export the masterkey file
    dfmaster = df.drop(['MRN', 'Phenotips_Family_ID'], axis=1)
    dfmaster.to_csv(fmasterkey, sep='\t', header=True, index=False)

    # Export the mrnorder file
    dfmrn = df.reset_index()
    dfmrn = dfmrn[['MRN', 'Subject_ID', 'Phenotips_Family_ID', 'Phenotips_ID']]
    #print("DF MRN ORDER:\n{}".format(dfmrn.head()))
    dfmrn.columns.values[1] = "Order_Number"
    #print("DF MRN ORDER:\n{}".format(dfmrn.head()))
    
    dfmrn.to_csv(fmrn, sep='\t', header=True, index=False)
    return(df)

# Write out a new pedigree file for the current release
def write_newped(df, ped, f):
    # Subset the full ped to the MRNs we have data for
    newped = ped.loc[df['MRN']]
    #print("DF:\n{}\n\n".format(df.head()))
    #print("Ped:\n{}\n\n".format(ped.head()))

    # Create a dictionary map of parent MRN to parent subject ID
    parents = set(pd.concat([newped['Father'], newped['Mother']]))
    parents = parents - set([0])
    parentIDs = df[df['MRN'].isin(parents)]
    parentIDs.reset_index(level=0, inplace=True)
    parentIDs = parentIDs[['MRN', 'Phenotips_ID']]
    parentIDs.set_index('MRN', inplace=True)
    parentIDs = parentIDs.to_dict()['Phenotips_ID']
    parentIDs['0']='0'
    #print("Parents Dict:\n{}".format(parentIDs))
    
    # Remap the parental MRNs to Phenotips_ID
    newped = newped.replace(parentIDs)

    # merge the phenotips data and the full pedigree
    newped = pd.merge(newped, df, how='inner', left_index=True, right_on='MRN')

    # Subset to the relevant columns
    theCols = ['Phenotips_Family_ID', 'Phenotips_ID', 'Father','Mother','Gender','Affected']
    newped = newped[theCols]
    #print("Final newped:\n{}".format(newped.head()))

    # Export the file
    newped.to_csv(f, sep='\t', header=False, index=False)

    return(newped)

####################################
# 
# Main 
#
####################################

def main():
    # Global variables
    global batch
    global testmode
    global config
    global stars
    stars = "******************************************"

    #
    # Usage statement
    #
    parseStr = 'Reads a list of available files, performs quality control on the data,\n\
    and outputs the files needed for GRIS.\n\n\
    Usage:\n\
        ncs_to_gris.py -b batch -c config_file \n\n\
    Example:\n\
        ncs_to_gris.py -b 7 -c batch7.config\n'

    
    parser = argparse.ArgumentParser(description=parseStr, formatter_class=RawTextHelpFormatter)
    parser.add_argument('-c', '--config_file', required=True, nargs='?', 
                        type=argparse.FileType('r'), default=None, 
                        help='Input configuration file containing source filenames and other information')
    parser.add_argument('-b', '--batch', required=True, type=int, help='Batch number (integer)')
    parser.add_argument('-t', '--testmode', required=False, action='store_true', default=False,
                        help='Run in test mode')

    args = parser.parse_args()
    config_file = args.config_file
    batch = str(args.batch)
    testmode=args.testmode

    #####################################
    #
    # Set up the variables and the log file
    #
    #####################################

    # Set up the log file
    thedate = str(datetime.datetime.now()).split()[0]
    thedate = re.sub("-","",thedate)
    global log 
    log = open('ncs_to_gris' + '.log', 'a')
    log.write('\n' + str(datetime.datetime.now()) + '\n')
    log.write(' '.join(sys.argv) + '\n')
    log.write('ncs_to_gris.py version ' + __version__ + '\n\n')
    log.flush()

    #####################################
    #
    # Load the Config File, and check it is complete
    #
    #####################################
    config = load(config_file)
    config = dict((k.lower(), v) for k, v in config.items())

    required_values = ['mapping', 'samplekey', 'pedigree', 'manifest', 'masterpedigree']
    missing = []
    for i in required_values:
        if i not in config.keys():
            missing.append(i)
    if len(missing) > 0:
        err_out("Configuration file, {}, is missing required value(s):\n{}\nPlease correct the config file and try again.\n".format(config_file.name, "\n".join(missing)))

    # add to the config variables
    config['bsi1'] = 'bsi1.csv'
    config['bsi2'] = 'bsi2.csv'
    config['bsi3'] = 'bsi3.csv'
    config['readme'] = 'README'
    config['masterkey'] = 'masterkey_batch' + batch + '.txt'
    config['newpedigree'] = 'seqr_ped_batch' + batch + '.txt'
    config['mrnorder'] = 'batch' + batch + '.txt'
    config['config_fname'] = config_file.name

    #####################################
    ##
    ## Import each of the reference files, do pedigree first to find the duplicate sample
    ## Q? Will the columns and the field names be consistent over time?
    ##
    #####################################
    send_update("Importing information from Pedigree, Sample Mapping, Sample Key, and Manifest files...", log)

    #
    # Read the Pedigree information, find the duplicate sample id, and get the batch information
    #
    send_update("Importing pedigree information from file: {}".format(config['pedigree']), log, True)
    batches, theDupe = import_pedigree(config['pedigree'])
    #print("Batches:\n{}".format(batches.head()))

    #
    # Read the original Manifest information
    #
    send_update("Importing original sample manifest information from file: {}".format(config['manifest']), log, True)
    manifest = import_manifest(config['manifest'], theDupe)
    #print("Manifest data:\n{}".format(manifest.tail()))

    #
    # Read the Sample Mapping information
    #
    send_update("Importing sample mapping information from file: {}".format(config['mapping']), log, True)
    mapping, theControl = import_samplemapping(config['mapping'], theDupe, findControl=True)
    #print("Mapping Data:\n{}".format(mapping.head()))

    #
    # Read the Master Sample Key information
    #
    send_update("Importing master sample key information from file: {}".format(config['samplekey']), log, True)
    samplekey = import_samplekey(config['samplekey'], theDupe, theControl)
    #print("Sample Key data:\n{}".format(samplekey.head()))

    #
    # Read the Order information
    #
    send_update("Importing received orders information from file: {}".format(config['orders']), log, True)
    orders = import_orders(config['orders'])
    #print("Orders data:\n{}".format(orders.head()))

    #
    # Read the full pedigree for family information
    #
    send_update("Importing complete pedigree information for all batches from file: {}".format(config['masterpedigree']), log, True)
    fullped = import_fullpedigree(config['masterpedigree'])
    #print("Full Pedigree data:\n{}".format(fullped.head()))


    ######################################
    #
    # Compare Subject_IDs in pedigree, mapping, samplekey files
    #
    ######################################
    send_update("Comparing the Subject_IDs from the pedigree, sample mapping, sample key, and orders files...", log)
        
    # Pedigree vs Sample Key
    ped_not_key, key_not_ped = compare_keys(samplekey, batches)

    # Mapping vs Sample Key
    mapping_not_key, key_not_mapping = compare_keys(samplekey, mapping)

    # Pedigree vs Orders
    ped_not_order, order_not_ped = compare_keys(orders, batches)

    # Manifest vs Sample Key
    #manifest_not_key, key_not_manifest = compare_keys(samplekey, manifest)
    #print("Manifest vs. Keys:\nManifest Only\n{}\nKeys only\n{}".format(manifest_not_key,key_not_manifest))


    # if they are different, error out until they are fixed
    # don't test ped_not_order - because these are ones released from previous batches, which we expect.
    if sum([len(ped_not_key), len(key_not_ped), len(mapping_not_key), len(key_not_mapping)]) > 0:
            #len(ped_not_order), len(order_not_ped)]) > 0:
        send_update("Missing {} key(s) in Pedigree not Sample Key {}: ".format(str(len(ped_not_key)), ped_not_key), log)
        send_update("Missing {} key(s) in Sample Key not Pedigree {}: ".format(str(len(key_not_ped)), key_not_ped), log)
        send_update("Missing {} key(s) in Sample Mapping not Sample Key {}: ".format(str(len(mapping_not_key)), mapping_not_key), log)
        send_update("Missing {} key(s) in Sample Key not Sample Mapping {}: ".format(str(len(key_not_mapping)), key_not_mapping), log)
        #send_update("Missing {} key(s) in Pedigree not Orders {}: ".format(str(len(ped_not_order)), ped_not_order), log)
        send_update("Missing {} key(s) in Orders not Pedigree {}: ".format(str(len(order_not_ped)), order_not_ped), log)
        
        #err_out("Error: Subject_IDs in pedigree, sample mapping, sample key, and order files are inconsistent.\n" + \
        #        "Please correct the Subject_IDs before continuing to process the data", log)
        pause_for_input("Error: Subject_IDs in pedigree, sample mapping, sample key, and order files are inconsistent.\n" + \
                "Please enter 'y' to continue processing the data, or 'q' to quit and correct the data.\n", 'y', 'q', log)
    else:
        send_update("Great News!! Subject_IDs in pedigree, sample mapping, and sample key files are consistent.\n", log)
#    if sum(len(ped_not_order), len(order_not_ped)) > 0:
#        send_update("Samples have been released with these data that are not in the current BSI Order.\n" + \
#        "Please update the batch_orders.csv file including the CIDR IDs listed below.\n"


    ######################################
    #
    # What is new in the batch and what is missing from the batch
    #
    ######################################


    ######################################
    #
    # For each subject, get all the MRNs in the same family
    #
    ######################################
    # Sort out who is from which batch
    send_update("Assessing subjects added to or dropped from Batch {}...".format(str(batch)), log, True)
    added_to_batch, dropped_from_batch = compare_keys(manifest, batches)
    #print("Added to batch:\n{}\n\nDropped from batch:\n{}".format(", ".join(added_to_batch), ", ".join(dropped_from_batch)))

    # Use the orders to get the MRNs, and use those to return the family IDs, and around again to all MRNs
    send_update("\nSearching for data on family members not released with the current batch...", log)

    # get all the family ids for these patients, and all released patients in these families
    families = list(set(fullped.loc[orders.tolist()]['Family_ID'].tolist()))
    familiesped = fullped[fullped['Family_ID'].isin(families)]
    allmrns = familiesped.index.values.tolist()

    # Get the Phenotips information for the subjects released in this batch
    bsi = get_bsi_data(config['bsi1'], config['bsi2'], allmrns, added_to_batch, dropped_from_batch)
    #print("BSI:\n{}".format(bsi.head()))

    # Merge everything you can into one big dataframe for subsetting later
    masterDF = create_master_df(bsi, mapping, familiesped)
    #print("MasterDF:\n{}".format(masterDF.head()))

    # Check that the Pedigree and BSI family IDs map one-to-one
    families_ok = check_family_ids(masterDF[masterDF['MRN'].isin(allmrns)])

    # which MRNs are in the orders and which are not
    ordermrns = orders.values.tolist()
    missing_orders = set(allmrns) - set(ordermrns)
    #print("Missing Orders: {}\n".format(missing_orders))
    orders_no_ped = set(ordermrns) - set(allmrns)
    mrns_pedandorders = set(ordermrns) & set(allmrns)
    if len(orders_no_ped) > 0:
        err_out("Error: Pedigree file is missing {} MRN(s) that were included in the orders file:{}".format(str(len(orders_no_ped)), orders_no_ped) + f, log)
    send_update("Batch {} orders file is missing {} MRNs".format(str(batch),str(len(missing_orders))), log, True)

    #
    # Print out the adds and drops to README
    #
    readme = open(config['readme'], 'w')
    #print("Write batch info")
    theText = write_batch_info(added_to_batch, dropped_from_batch, batches, masterDF, readme)

    ######################################
    #   
    # Now create the master key file for subsetting from the full VCF
    #
    ######################################

    # Master key file: 
    # Get the CIDR Exome ID from previous mapping files for family members
    send_update("Writing out the MasterKey and OrderMRN files: {}...".format(config['masterkey']), log)
    newkey = write_keys(masterDF, allmrns, missing_orders, fullped, bsi, config['masterkey'], config['mrnorder'], readme)

    send_update("Writing out new Pedigree file: {}...".format(config['newpedigree']), log)
    newped = write_newped(newkey, fullped, config['newpedigree'])
    
    #print("Write family info")
    write_family_info(newped, batches, families, allmrns, readme)

    ######################################
    #   
    # Close out and clean up
    #
    ######################################
    send_update("\nncs_to_gris.py successfully completed", log)
    send_update(str(datetime.datetime.now()) + '\n', log)
    log.close()

if __name__ == '__main__':
    main()


