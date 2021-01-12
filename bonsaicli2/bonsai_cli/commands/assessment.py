"""
This file contains the code for commands that target a bonsai assessment in brain_version 2 of the bonsai command line.
"""
__author__ = "Karthik Sankara Subramanian"
__copyright__ = "Copyright 2020, Microsoft Corp."

import click
from datetime import timedelta
import json
from json import dumps
import re
from tabulate import tabulate
from typing import Optional

from bonsai_cli.exceptions import AuthenticationError, BrainServerError
from bonsai_cli.utils import (
    api,
    get_latest_brain_version,
    get_version_checker,
    raise_as_click_exception,
    raise_brain_server_error_as_click_exception,
    raise_unique_constraint_violation_as_click_exception,
    raise_not_found_as_click_exception,
)


@click.group()
def assessment():
    """Brain version assessment operations."""
    pass


@click.command("start", short_help="Start running an assessment.")
@click.pass_context
@click.option("--brain-name", "-b", help="[Required] Name of the brain.")
@click.option("--concept-name", "-c", help="[Required] Concept to assess.")
@click.option(
    "--file",
    "-f",
    help="[Required] Path to JSON assessment configuration file containing episode configurations.",
)
@click.option(
    "--brain-version",
    type=int,
    help="The version of the brain to start assessing, defaults to latest",
)
@click.option(
    "--name",
    "-n",
    help="Name of the assessment, defaults to an autogenerated name.",
)
@click.option("--display-name", help="Display name of the assessment.")
@click.option("--description", "-des", help="Description for the assessment.")
@click.option(
    "--maximum-duration",
    help="Maximum time duration the assessment should run for. Defaults to 24 hours, maximum allowed duration is 7 days. "
    "Format should be <duration><unit>. Units can be days (d), hours (h), or minutes (m), defaults to hours.",
)
@click.option(
    "--episode-iteration-limit",
    type=int,
    help="Maximum number of iterations per assessment episode, defaults to 1000.",
)
@click.option(
    "--simulator-package-name",
    help="Simulator package to use for assessment in the case of managed simulators.",
)
@click.option(
    "--instance-count",
    "-i",
    type=int,
    help="Number of simulator instances to perform assessment with, in the case of managed simulators",
)
@click.option(
    "--workspace-id",
    "-wid",
    help="Please provide the workspace id if you would like to override the default target workspace.",
    hidden=True,
)
@click.option(
    "--debug", default=False, is_flag=True, help="Verbose logging for request."
)
@click.option("--output", "-o", help="Set output, only json supported.")
@click.option(
    "--test",
    default=False,
    is_flag=True,
    help="Enhanced response for testing.",
    hidden=True,
)
def start_assessment(
    ctx: click.Context,
    brain_name: str,
    concept_name: str,
    file: str,
    brain_version: int,
    name: str,
    display_name: str,
    description: str,
    maximum_duration: str,
    episode_iteration_limit: int,
    simulator_package_name: str,
    instance_count: str,
    workspace_id: str,
    debug: bool,
    output: str,
    test: bool,
):
    brain_version_checker = get_version_checker(ctx, interactive=not output)

    error_msg = ""
    required_options_provided = True

    if not brain_name:
        required_options_provided = False
        error_msg += "\nName of the brain is required"

    if not concept_name:
        required_options_provided = False
        error_msg += "\nConcept name is required"

    if not file:
        required_options_provided = False
        error_msg += "\nPath to JSON assessment configuration file is required"

    if not maximum_duration:
        maximum_duration = str(24)

    maximum_duration_in_minutes = 0

    if maximum_duration:
        duration = parse_duration(maximum_duration)

        if duration:
            maximum_duration_in_minutes = (duration.days * 1440) + int(
                duration.seconds / 60
            )

        else:
            required_options_provided = False
            error_msg += "\nInvalid format for maximum_duration. Please use suffix 'm' if specifying in minutes OR suffix 'h' if specifying in hours OR suffix 'd' if specifying in days."

    if not required_options_provided:
        raise_as_click_exception(error_msg)

    if not brain_version:
        brain_version = get_latest_brain_version(
            brain_name,
            "Start assessment {} of for brain {} brain_version {}".format(
                name, brain_name, brain_version
            ),
            debug,
            output,
            test,
        )

    try:
        f = open(file, "r")
        configuration_file_content = f.read()
        f.close()

    except FileNotFoundError as e:
        raise_as_click_exception(e)

    except Exception as e:
        raise_as_click_exception(e)

    try:
        configuration = json.loads(configuration_file_content)

    except Exception as e:
        raise_as_click_exception("Error reading JSON in {}: {}".format(file, e))

    if not episode_iteration_limit:
        episode_iteration_limit = 1000

    try:
        response = api(use_aad=True).start_assessmentv2(
            name=name,
            brain_name=brain_name,
            version=brain_version,
            concept_name=concept_name,
            scenarios=configuration,
            episode_iteration_limit=episode_iteration_limit,
            maximum_duration_in_minutes=maximum_duration_in_minutes,
            display_name=display_name,
            description=description,
            workspace=workspace_id,
            debug=debug,
        )

    except BrainServerError as e:
        if "Unique index constraint violation" in str(e):
            raise_unique_constraint_violation_as_click_exception(
                debug, output, "Assessment", name, test, e
            )
        else:
            raise_as_click_exception(e)

    except AuthenticationError as e:
        raise_as_click_exception(e)

    if simulator_package_name:
        try:
            show_simulator_package_response = api(use_aad=True).get_sim_package(
                simulator_package_name,
                workspace=workspace_id,
                debug=debug,
                output=output,
            )
        except BrainServerError as e:
            if e.exception["statusCode"] == 404:
                raise_not_found_as_click_exception(
                    debug,
                    output,
                    "Starting managed simulator",
                    "Simulator package",
                    simulator_package_name,
                    test,
                    e,
                )
            else:
                raise_brain_server_error_as_click_exception(debug, output, test, e)

        except AuthenticationError as e:
            raise_as_click_exception(e)

        cores_per_instance = show_simulator_package_response["coresPerInstance"]
        memory_in_gb_per_instance = show_simulator_package_response[
            "memInGbPerInstance"
        ]
        min_instance_count = show_simulator_package_response["minInstanceCount"]
        max_instance_count = show_simulator_package_response["maxInstanceCount"]
        auto_scaling = show_simulator_package_response["autoScale"]
        auto_termination = show_simulator_package_response["autoTerminate"]

        if not instance_count:
            instance_count = show_simulator_package_response["startInstanceCount"]

        try:
            api(use_aad=True).create_sim_collection(
                packagename=simulator_package_name,
                brain_name=brain_name,
                brain_version=brain_version,
                purpose_action="Assess",
                concept_name=concept_name,
                description="desc",
                cores_per_instance=cores_per_instance,
                memory_in_gb_per_instance=memory_in_gb_per_instance,
                start_instance_count=instance_count,
                min_instance_count=min_instance_count,
                max_instance_count=max_instance_count,
                auto_scaling=auto_scaling,
                auto_termination=auto_termination,
                workspace=workspace_id,
                debug=debug,
            )

        except BrainServerError as e:
            raise_brain_server_error_as_click_exception(debug, output, test, e)

    status_message = "Started assessment {} of brain {} version {}.".format(
        response["name"], brain_name, brain_version
    )

    if output == "json":
        json_response = {
            "status": response["status"],
            "statusCode": response["statusCode"],
            "statusMessage": status_message,
        }

        if test:
            json_response["elapsed"] = str(response["elapsed"])
            json_response["timeTaken"] = str(response["timeTaken"])

        click.echo(dumps(json_response, indent=4))

    else:
        click.echo(status_message)

    brain_version_checker.check_cli_version(wait=True, print_up_to_date=False)


@click.command(
    "list",
    short_help="List all assessments for this brain version.",
)
@click.option(
    "--brain-name",
    "-b",
    help="[Required] Name of the brain.",
)
@click.option(
    "--brain-version",
    type=int,
    help="The version of the brain to list, defaults to latest.",
)
@click.option(
    "--workspace-id",
    "-wid",
    help="Please provide the workspace id if you would like to override the default target workspace.",
    hidden=True,
)
@click.option(
    "--debug", default=False, is_flag=True, help="Verbose logging for request."
)
@click.option("--output", "-o", help="Set output, only json supported.")
@click.option(
    "--test",
    default=False,
    is_flag=True,
    help="Enhanced response for testing.",
    hidden=True,
)
@click.pass_context
def list_assessment(
    ctx: click.Context,
    brain_name: str,
    brain_version: int,
    workspace_id: str,
    debug: bool,
    output: str,
    test: bool,
):
    brain_version_checker = get_version_checker(ctx, interactive=not output)

    if not brain_name:
        raise_as_click_exception(
            "Name of the brain for which assessments are to be listed is required"
        )

    if not brain_version:
        brain_version = get_latest_brain_version(
            brain_name,
            "List assessment brain {} brain_version {}".format(
                brain_name, brain_version
            ),
            debug,
            output,
            test,
        )

    try:
        response = api(use_aad=True).list_assessment(
            workspace=workspace_id,
            brain_name=brain_name,
            version=brain_version,
            debug=debug,
        )

    except BrainServerError as e:
        raise_brain_server_error_as_click_exception(debug, output, test, e)

    except AuthenticationError as e:
        raise_as_click_exception(e)

    if len(response["value"]) == 0:
        click.echo(
            "No assessments exist for brain {} version {}".format(
                brain_name, brain_version
            )
        )
        ctx.exit()

    rows = []
    dict_rows = []
    for item in response["value"]:
        try:
            assessment_name = item["name"]
            status = get_assessment_status(item["state"])
            description = item["description"]

            rows.append([assessment_name, status, description])
            dict_rows.append(
                {
                    "assessmentName": assessment_name,
                    "status": status,
                    "description": description,
                }
            )
        except KeyError:
            pass  # If it's missing a field, ignore it.

    if output == "json":
        json_response = {
            "value": dict_rows,
            "status": response["status"],
            "statusCode": response["statusCode"],
            "statusMessage": "",
        }

        if test:
            json_response["elapsed"] = str(response["elapsed"])
            json_response["timeTaken"] = str(response["timeTaken"])

        click.echo(dumps(json_response, indent=4))

    else:
        table = tabulate(
            rows,
            headers=["Assessment Name", "Status", "Description"],
            tablefmt="orgtbl",
        )
        click.echo(table)

    brain_version_checker.check_cli_version(wait=True, print_up_to_date=False)


@click.command("show", short_help="Show information about an assessment.")
@click.option("--name", "-n", help="[Required] Name of the assessment.")
@click.option(
    "--brain-name",
    "-b",
    help="[Required] Name of the brain.",
)
@click.option(
    "--brain-version",
    type=int,
    help="The version of the brain to show, defaults to latest.",
)
@click.option(
    "--workspace-id",
    "-wid",
    help="Please provide the workspace id if you would like to override the default target workspace.",
    hidden=True,
)
@click.option(
    "--debug", default=False, is_flag=True, help="Verbose logging for request."
)
@click.option("--output", "-o", help="Set output, only json supported.")
@click.option(
    "--test",
    default=False,
    is_flag=True,
    help="Enhanced response for testing.",
    hidden=True,
)
@click.pass_context
def show_assessment(
    ctx: click.Context,
    name: str,
    brain_name: str,
    brain_version: int,
    workspace_id: str,
    debug: bool,
    output: str,
    test: bool,
):
    brain_version_checker = get_version_checker(ctx, interactive=not output)

    error_msg = ""
    required_options_provided = True

    if not name:
        required_options_provided = False
        error_msg += "\nName of the assessment is required"

    if not brain_name:
        required_options_provided = False
        error_msg += "\nName of the brain is required"

    if not required_options_provided:
        raise_as_click_exception(error_msg)

    if not brain_version:
        brain_version = get_latest_brain_version(
            brain_name,
            "Show assessment {} of brain {} version {}".format(
                name, brain_name, brain_version
            ),
            debug,
            output,
            test,
        )

    try:
        response = api(use_aad=True).get_assessment(
            name=name,
            brain_name=brain_name,
            version=brain_version,
            workspace=workspace_id,
            debug=debug,
        )

    except BrainServerError as e:
        if "not found" in str(e):
            raise_not_found_as_click_exception(
                debug, output, "show", "Assessment", name, test, e
            )

        else:
            raise_brain_server_error_as_click_exception(debug, output, test, e)

    except AuthenticationError as e:
        raise_as_click_exception(e)

    if output == "json":
        json_response = {
            "assessmentName": response["name"],
            "displayName": response["displayName"],
            "description": response["description"],
            "status": get_assessment_status(response["state"]),
            "runTime": response["runTime"],
            "concept": response["concept"],
            "conceptLesson": response["lessonIndex"],
            "createdOn": response["createdTimeStamp"],
            "modifiedOn": response["modifiedTimeStamp"],
            "statusCode": response["statusCode"],
            "statusMessage": "",
        }

        click.echo(dumps(json_response, indent=4))

    else:
        click.echo("Assessment Name: {}".format(response["name"]))
        click.echo("Display Name: {}".format(response["displayName"]))
        click.echo("Description: {}".format(response["description"]))
        click.echo("Status: {}".format(get_assessment_status(response["state"])))
        click.echo("Run Time: {}".format(response["runTime"]))
        click.echo("Concept: {}".format(response["concept"]))
        click.echo("Concept Lesson: {}".format(response["lessonIndex"]))
        click.echo("Created On: {}".format(response["createdTimeStamp"]))
        click.echo("Modified On: {}".format(response["modifiedTimeStamp"]))

    brain_version_checker.check_cli_version(wait=True, print_up_to_date=False)


@click.command("get-configuration", short_help="Get assessment configuration file.")
@click.option("--name", "-n", help="[Required] Name of the assessment.")
@click.option(
    "--brain-name",
    "-b",
    help="[Required] Name of the brain.",
)
@click.option(
    "--brain-version",
    type=int,
    help="The version of the brain to get configurations from, defaults to latest.",
)
@click.option(
    "--file",
    "-f",
    help="File to write assessment configuration to, defaults to console output.",
)
@click.option(
    "--workspace-id",
    "-wid",
    help="Please provide the workspace id if you would like to override the default target workspace.",
    hidden=True,
)
@click.option(
    "--debug", default=False, is_flag=True, help="Verbose logging for request."
)
@click.option("--output", "-o", help="Set output, only json supported.")
@click.option(
    "--test",
    default=False,
    is_flag=True,
    help="Enhanced response for testing.",
    hidden=True,
)
@click.pass_context
def get_configuration_assessment(
    ctx: click.Context,
    name: str,
    brain_name: str,
    brain_version: int,
    file: str,
    workspace_id: str,
    debug: bool,
    output: str,
    test: bool,
):
    brain_version_checker = get_version_checker(ctx, interactive=not output)

    error_msg = ""
    required_options_provided = True

    if not name:
        required_options_provided = False
        error_msg += "\nName of the assessment is required"

    if not brain_name:
        required_options_provided = False
        error_msg += "\nName of the brain is required"

    if not required_options_provided:
        raise_as_click_exception(error_msg)

    if not brain_version:
        brain_version = get_latest_brain_version(
            brain_name,
            "Get-configuration assessment {} of brain {} version {}".format(
                name, brain_name, brain_version
            ),
            debug,
            output,
            test,
        )

    try:
        response = api(use_aad=True).get_assessment(
            name=name,
            brain_name=brain_name,
            version=brain_version,
            workspace=workspace_id,
            debug=debug,
        )

    except BrainServerError as e:
        if "not found" in str(e):
            raise_not_found_as_click_exception(
                debug, output, "Get-configuration", "Assessment", name, test, e
            )

        else:
            raise_brain_server_error_as_click_exception(debug, output, test, e)

    except AuthenticationError as e:
        raise_as_click_exception(e)

    if file:
        f = open(file, "w+")
        f.write(str(response["scenarios"]))
        f.close()

        status_message = "Assessment configuration saved from assessment {} brainn {} version {} to {}.".format(
            name, brain_name, brain_version, file
        )
        if output == "json":
            json_response = {
                "status": response["status"],
                "statusCode": response["statusCode"],
                "statusMessage": status_message,
            }

            if test:
                json_response["elapsed"] = str(response["elapsed"])
                json_response["timeTaken"] = str(response["timeTaken"])

            click.echo(dumps(json_response, indent=4))

        else:
            click.echo(status_message)
    else:
        if output == "json":
            json_response = {
                "status": response["status"],
                "statusCode": response["statusCode"],
                "configuration": response["scenarios"],
            }

            if test:
                json_response["elapsed"] = str(response["elapsed"])
                json_response["timeTaken"] = str(response["timeTaken"])

            click.echo(dumps(json_response, indent=4))

        else:
            click.echo(response["scenarios"])

    brain_version_checker.check_cli_version(wait=True, print_up_to_date=False)


@click.command("update", short_help="Update information about an assessment.")
@click.option("--name", "-n", help="[Required] Name of the assessment.")
@click.option(
    "--brain-name",
    "-b",
    help="[Required] Name of the brain.",
)
@click.option(
    "--brain-version",
    type=int,
    help="The version of the brain to update, defaults to latest.",
)
@click.option("--display-name", help="Display name of the assessment.")
@click.option("--description", "-des", help="Description for the assessment.")
@click.option(
    "--workspace-id",
    "-wid",
    help="Please provide the workspace id if you would like to override the default target workspace.",
    hidden=True,
)
@click.option(
    "--debug", default=False, is_flag=True, help="Verbose logging for request."
)
@click.option("--output", "-o", help="Set output, only json supported.")
@click.option(
    "--test",
    default=False,
    is_flag=True,
    help="Enhanced response for testing.",
    hidden=True,
)
@click.pass_context
def update_assessment(
    ctx: click.Context,
    name: str,
    brain_name: str,
    brain_version: int,
    display_name: str,
    description: str,
    workspace_id: str,
    debug: bool,
    output: str,
    test: bool,
):
    brain_version_checker = get_version_checker(ctx, interactive=not output)

    error_msg = ""
    required_options_provided = True

    if not name:
        required_options_provided = False
        error_msg += "\nName of the assessment is required"

    if not brain_name:
        required_options_provided = False
        error_msg += "\nName of the brain is required"

    if not required_options_provided:
        raise_as_click_exception(error_msg)

    if not brain_version:
        brain_version = get_latest_brain_version(
            brain_name,
            "Update assessment {} of brain {} version {}".format(
                name, brain_name, brain_version
            ),
            debug,
            output,
            test,
        )

    try:
        response = api(use_aad=True).update_assessment(
            name,
            brain_name=brain_name,
            version=brain_version,
            display_name=display_name,
            description=description,
            workspace=workspace_id,
            debug=debug,
        )

    except BrainServerError as e:
        if "not found" in str(e):
            raise_not_found_as_click_exception(
                debug, output, "update", "Assessment", name, test, e
            )

        else:
            raise_brain_server_error_as_click_exception(debug, output, test, e)

    except AuthenticationError as e:
        raise_as_click_exception(e)

    status_message = "Updated assessment {} of brain {} version {}.".format(
        name, brain_name, brain_version
    )

    if output == "json":
        json_response = {
            "status": response["status"],
            "statusCode": response["statusCode"],
            "statusMessage": status_message,
        }

        if test:
            json_response["elapsed"] = str(response["elapsed"])
            json_response["timeTaken"] = str(response["timeTaken"])

        click.echo(dumps(json_response, indent=4))

    else:
        click.echo(status_message)

    brain_version_checker.check_cli_version(wait=True, print_up_to_date=False)


@click.command("stop", short_help="Stop running an assessment.")
@click.option("--name", "-n", help="[Required] Name of the assessment.")
@click.option(
    "--brain-name",
    "-b",
    help="[Required] Name of the brain.",
)
@click.option(
    "--brain-version",
    type=int,
    help="The version of the brain to stop, defaults to latest.",
)
@click.option(
    "--workspace-id",
    "-wid",
    help="Please provide the workspace id if you would like to override the default target workspace.",
    hidden=True,
)
@click.option(
    "--debug", default=False, is_flag=True, help="Verbose logging for request."
)
@click.option("--output", "-o", help="Set output, only json supported.")
@click.option(
    "--test",
    default=False,
    is_flag=True,
    help="Enhanced response for testing.",
    hidden=True,
)
@click.pass_context
def stop_assessment(
    ctx: click.Context,
    name: str,
    brain_name: str,
    brain_version: int,
    workspace_id: str,
    debug: bool,
    output: str,
    test: bool,
):
    brain_version_checker = get_version_checker(ctx, interactive=not output)

    error_msg = ""
    required_options_provided = True

    if not name:
        required_options_provided = False
        error_msg += "\nName of the assessment is required"

    if not brain_name:
        required_options_provided = False
        error_msg += "\nName of the brain is required"

    if not required_options_provided:
        raise_as_click_exception(error_msg)

    if not brain_version:
        brain_version = get_latest_brain_version(
            brain_name,
            "Stop assessment {} of brain {} brain_version {}".format(
                name, brain_name, brain_version
            ),
            debug,
            output,
            test,
        )

    try:
        response = api(use_aad=True).stop_assessment_v2(
            name,
            brain_name=brain_name,
            version=brain_version,
            state="cancelled",
            workspace=workspace_id,
            debug=debug,
        )

    except BrainServerError as e:
        if "not found" in str(e):
            raise_not_found_as_click_exception(
                debug, output, "stop", "Assessment", name, test, e
            )

        else:
            raise_brain_server_error_as_click_exception(debug, output, test, e)

    except AuthenticationError as e:
        raise_as_click_exception(e)

    status_message = "Stopped assessment {} of brain {} version {}.".format(
        name, brain_name, brain_version
    )

    if output == "json":
        json_response = {
            "status": response["status"],
            "statusCode": response["statusCode"],
            "statusMessage": status_message,
        }

        if test:
            json_response["elapsed"] = str(response["elapsed"])
            json_response["timeTaken"] = str(response["timeTaken"])

        click.echo(dumps(json_response, indent=4))

    else:
        click.echo(status_message)

    brain_version_checker.check_cli_version(wait=True, print_up_to_date=False)


@click.command("delete", short_help="Delete an assessment.")
@click.option("--name", "-n", help="[Required] Name of the assessment.")
@click.option(
    "--brain-name",
    "-b",
    help="[Required] Name of the brain.",
)
@click.option(
    "--brain-version",
    type=int,
    help="The version of the brain to delete, defaults to latest.",
)
@click.option(
    "--yes", "-y", default=False, is_flag=True, help="Do not prompt for confirmation."
)
@click.option(
    "--workspace-id",
    "-wid",
    help="Please provide the workspace id if you would like to override the default target workspace.",
    hidden=True,
)
@click.option(
    "--debug", default=False, is_flag=True, help="Verbose logging for request."
)
@click.option("--output", "-o", help="Set output, only json supported.")
@click.option(
    "--test",
    default=False,
    is_flag=True,
    help="Enhanced response for testing.",
    hidden=True,
)
@click.pass_context
def delete_assessment(
    ctx: click.Context,
    name: str,
    brain_name: str,
    brain_version: int,
    yes: bool,
    workspace_id: str,
    debug: bool,
    output: str,
    test: bool,
):
    brain_version_checker = get_version_checker(ctx, interactive=not output)

    error_msg = ""
    required_options_provided = True

    if not name:
        required_options_provided = False
        error_msg += "\nName of the assessment is required"

    if not brain_name:
        required_options_provided = False
        error_msg += "\nName of the brain is required"

    if not required_options_provided:
        raise_as_click_exception(error_msg)

    if not brain_version:
        brain_version = get_latest_brain_version(
            brain_name,
            "Delete assessment {} of brain {} brain_version {}".format(
                name, brain_name, brain_version
            ),
            debug,
            output,
            test,
        )

    is_delete = False

    if not yes:
        click.echo(
            "Are you sure you want to delete assessment {} of brain {} version {} (y/n?).".format(
                name, brain_name, brain_version
            )
        )
        choice = input().lower()

        yes_set = {"yes", "y"}
        no_set = {"no", "n"}

        if choice in yes_set:
            is_delete = True
        elif choice in no_set:
            is_delete = False
        else:
            raise_as_click_exception("\nPlease respond with 'y' or 'n'")

    else:
        is_delete = True

    if is_delete:
        try:
            response = api(use_aad=True).delete_assessment(
                name,
                brain_name=brain_name,
                version=brain_version,
                workspace=workspace_id,
                debug=debug,
            )

        except BrainServerError as e:
            raise_brain_server_error_as_click_exception(debug, output, test, e)

        except AuthenticationError as e:
            raise_as_click_exception(e)

        status_message = "Deleted assessment {} of brain {} version {}.".format(
            name, brain_name, brain_version
        )

        if output == "json":
            json_response = {
                "status": response["status"],
                "statusCode": response["statusCode"],
                "statusMessage": status_message,
            }

            if test:
                json_response["elapsed"] = str(response["elapsed"])
                json_response["timeTaken"] = str(response["timeTaken"])

            click.echo(dumps(json_response, indent=4))

        else:
            click.echo(status_message)

    brain_version_checker.check_cli_version(wait=True, print_up_to_date=False)


def get_assessment_status(state: str):
    status = ""

    if state.lower() == "active":
        status = "In progress"
    elif (
        state.lower() == "cancelled"
        or state.lower() == "complete"
        or state.lower() == "deadlineexceeded"
    ):
        status = "Complete"
    elif state.lower() == "error":
        status = "Error"

    return status


_DURATION_REGEX = re.compile(
    r"((?P<days>\d+?)d)?((?P<hours>\d+?)h)?((?P<minutes>\d+?)m)?"
)


def parse_duration(input: str) -> Optional[timedelta]:
    try:
        return timedelta(hours=int(input))
    except:
        pass

    parts = _DURATION_REGEX.match(input)

    if not parts:
        return None

    timedelta_kwargs = {}

    for (unit, value) in parts.groupdict().items():
        if value is not None:
            timedelta_kwargs.update({unit: int(value)})

    return timedelta(**timedelta_kwargs)


assessment.add_command(start_assessment)
assessment.add_command(show_assessment)
assessment.add_command(get_configuration_assessment)
assessment.add_command(update_assessment)
assessment.add_command(list_assessment)
assessment.add_command(delete_assessment)
assessment.add_command(stop_assessment)
