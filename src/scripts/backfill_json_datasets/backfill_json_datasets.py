"""
Submit Synapse files stored on an external S3 bucket to a Glue workflow.
Of course, this assumes that the workflow has read permissions on the S3
bucket.

If --synapse-parent is specified, all files in that folder are submitted to
the workflow. Otherwise, a --file-view must be specified (and optionally,
a --query, if you do not want to submit every file in the file view).
"""
import argparse
import boto3
import synapseclient


def read_args():
    parser = argparse.ArgumentParser(
            description=("Submit files on Synapse to an AWS --glue-workflow"))
    parser.add_argument("--synapse-parent",
                        help="The Synapse ID of the parent folder.")
    parser.add_argument("--file-view",
                        help=("The Synapse ID of a file view containing "
                              "files to be submitted."))
    parser.add_argument("--query",
                        help=("An f-string formatted query which filters the "
                              "file view. Use {source_table} in the FROM clause."))
    parser.add_argument("--glue-workflow",
                        help="The name of the Glue workflow to submit to.")
    parser.add_argument("--profile",
                        help="The AWS profile to use.")
    parser.add_argument("--ssm-parameter",
                        help=("The name of the SSM parameter containing "
                              "the Synapse personal access token. "
                              "If not provided, cached credentials are used"))
    args = parser.parse_args()
    return args


def get_synapse_client(ssm_parameter=None, aws_session=None):
    if ssm_parameter is not None:
        ssm_client = aws_session.client("ssm")
        token = ssm_client.get_parameter(
            Name=ssm_parameter,
            WithDecryption=True)
        syn = synapseclient.Synapse()
        syn.login(authToken=token["Parameter"]["Value"])
    else: # try cached credentials
        syn = synapseclient.login()
    return syn

def get_synapse_ids(syn, synapse_parent=None, entity_view=None, query=None):
    if synapse_parent is not None: # Submit all files in a folder
        children = syn.getChildren(
                parent=synapse_parent,
                includeTypes=["file"])
        synapse_ids = [child["id"] for child in children]
    elif entity_view is not None:
        if query is not None:
            query_string = query.format(source_table=entity_view)
        else:
            query_string = f"select * from {entity_view}"
        synapse_q = syn.tableQuery(query_string)
        synapse_df = synapse_q.asDataFrame()
        synapse_ids = synapse_df["id"].values
    else:
        raise ValueError("Either synapse_parent or entity_view must be defined.")
    return synapse_ids


def submit_archives_to_workflow(syn, synapse_ids, glue_workflow, aws_session):
    glue_client = aws_session.client("glue")
    for synapse_id in synapse_ids:
        s3_loc = get_s3_loc(
                syn=syn,
                synapse_id=synapse_id)
        workflow_run = glue_client.start_workflow_run(Name=glue_workflow)
        glue_client.put_workflow_run_properties(
                Name=glue_workflow,
                RunId=workflow_run["RunId"],
                RunProperties={
                    "input_bucket": s3_loc["bucket"],
                    "input_key": s3_loc["key"]})


def get_s3_loc(syn, synapse_id):
    f = syn.get(synapse_id, downloadFile=False)
    bucket = f["_file_handle"]["bucketName"]
    key = f["_file_handle"]["key"]
    s3_loc = {"bucket": bucket, "key": key}
    return s3_loc


def main():
    args = read_args()
    aws_session = boto3.session.Session(profile_name=args.profile)
    syn = get_synapse_client(
            ssm_parameter=args.ssm_parameter,
            aws_session=aws_session)
    synapse_ids = get_synapse_ids(
            syn=syn,
            synapse_parent=args.synapse_parent,
            entity_view=args.file_view,
            query=args.query)
    submit_archives_to_workflow(
            syn=syn,
            synapse_ids=synapse_ids,
            glue_workflow=args.glue_workflow,
            aws_session=args.aws_session)

if __name__ == "__main__":
    main()
