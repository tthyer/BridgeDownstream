'''
This script creates a Synpase project, connects to an existing S3 bucket,
and syncs test data files to the project.
'''
import json
import logging
import sys
from pathlib import Path

import boto3
import synapseclient
from synapseclient import File
from synapseformation import client as synapseformation_client

project_name = 'BridgeDownstreamTest'

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def get_synapse_client(ssm_parameter):
  '''Get an instance of the synapse client'''
  ssm_client = boto3.client('ssm')
  token = ssm_client.get_parameter(
    Name=ssm_parameter,
    WithDecryption=True)
  syn = synapseclient.Synapse()
  synapse_auth_token = token['Parameter']['Value']
  syn.login(authToken=synapse_auth_token, silent=True)
  return syn


def get_project_id(syn, principal_id):
  '''Get the id of the synapse project if it exists'''
  logger.info(f'Getting Synapse project id for {project_name}')
  projects = syn.restGET(f'/projects/user/{principal_id}')
  BridgeDownstreamTest = next(
    filter(
      lambda x: x['name'] == project_name,
      projects.get('results')
      ),
    None)
  return '' if BridgeDownstreamTest is None else BridgeDownstreamTest.get('id')


def create_project(syn, template_path):
  '''Create a synapse project from a template'''
  logger.info(f'Creating Synapse project {project_name}, ' +
    f'with template_path {template_path}')
  try:
    response = synapseformation_client.create_synapse_resources(syn, template_path)
    logger.debug(f'Project response: {response}')
    if response is not None:
      return response.get('id')
  except Exception as e:
      logger.error(e)
      sys.exit(1)


def setup_external_storage(syn, bucket_name, project_id, folder_id):
  '''Connect bucket as external storage for the Synapse project'''
  logger.info(f'Setting s3 bucket {bucket_name} as storage for {project_name}, ' +
    f'with Synapse folder {folder_id}.')
  storage_location = syn.create_s3_storage_location(
          parent = project_id,
          folder = folder_id,
          bucket_name = bucket_name,
          sts_enabled=True)
  storage_location_info = {
         k: v for k, v in
         zip(['synapse_folder', 'storage_location', 'synapse_project'],
             storage_location)}
  return(storage_location_info)


def get_folder_id(syn, project_id, synapse_folder_name):
  logger.info(f'Getting synapse id for {synapse_folder_name} folder, ' +
    f'child of project {project_id}')
  response = list(syn.getChildren(project_id, includeTypes=['folder']))
  folder = next(item for item in response if item['name'] == synapse_folder_name)
  return '' if folder is None else folder.get('id')


def add_test_data(syn, dir_path, bucket_name, folder_id):
  '''Upload files to S3 then create handles in Synapse'''
  data_dir = f'{dir_path}/data'
  files = (item for item in Path(data_dir).iterdir() if item.is_file())

  with open(f'{dir_path}/metadata.json') as metadata_file:
      metadata = json.load(metadata_file)
  s3 = boto3.resource('s3')
  bucket = s3.Bucket(bucket_name)
  for file_path in files:
      filename = file_path.parts[-1]
      file_metadata = metadata[filename]
      logger.info(f'Adding {filename} to S3 bucket {bucket_name}')
      with open(file_path, 'rb') as f:
          bucket.put_object(
              Body=f,
              Key=filename,
              Metadata=file_metadata
          )
      logger.info(f'Storing {filename} as handle in folder {folder_id}')
      file_handle=syn.create_external_s3_file_handle(
          bucket_name=bucket_name,
          s3_file_key=filename,
          file_path=file_path,
          parent=folder_id)
      file = File(
          parentId=folder_id,
          name=filename,
          synapseStore=False,
          dataFileHandleId=file_handle['id'])
      syn.store(file)


def main():

  logger.info(f'Begin setting up test data')

  # get synapse client
  ssm_parameter = 'synapse-bridgedownstream-auth'
  syn = get_synapse_client(ssm_parameter=ssm_parameter)

  # see if project exists and get its id

  principal_id = '3432808' # BridgeDownstream Synapse service account
  project_id = get_project_id(syn, principal_id)

  # if there's a project id, assume the project is already connected to synapse
  connected_to_synapse = True if project_id else False

  # if no project id is available, create a new project
  if not project_id:
    template_path = './src/scripts/setup_test_data/synapse-formation.yaml'
    create_project(syn, template_path)
    project_id = get_project_id(syn, principal_id)

  # get folder synapse id
  synapse_folder_name = 'test-data'
  folder_id = get_folder_id(syn, project_id, synapse_folder_name)
  logger.debug(f'folder_id: {folder_id}')

  # connect bucket and project if this is a newly made project
  bucket_name = 'bridge-downstream-dev-source'
  if not connected_to_synapse:
    storage_location_info = setup_external_storage(syn, bucket_name, project_id, folder_id)
    logger.debug(f'storage_location_info: {storage_location_info}')

  # add test data to Synapse
  script_dir = './src/scripts/setup_test_data'
  add_test_data(syn, script_dir, bucket_name, folder_id)


if __name__ == "__main__":
  main()
