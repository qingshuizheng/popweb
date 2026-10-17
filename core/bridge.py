"""The Emacs side of the conversation, as seen from Python.

Every module that needs a value from Emacs -- an option, the theme background,
a function result -- goes through this module, which owns the EPC client and
the encoding rules.

Strings are encoded as Base64 of their UTF-8 bytes before they are handed to
EPC.  That is required, not cosmetic: the Emacs side reads each argument back
as a Lisp form, so a translation containing a quote or a parenthesis would
otherwise be read as code.  Booleans take a different path, because EPC turns
a Lisp nil into an empty list, which cannot be told apart from "false"; the
`get-emacs-var' reply therefore carries a second element that says whether the
value was a boolean.
"""

from __future__ import annotations

import base64
import os
import traceback
from typing import Any, List

from epc.client import EPCClient

epc_client: EPCClient | None = None

emacs_config_dir = ""


def init_epc_client(emacs_server_port: int) -> None:
    """Connect to the EPC server of Emacs listening on EMACS_SERVER_PORT.

    Calling this twice keeps the first connection.  A refused connection is
    reported with its traceback and leaves the module without a client, which
    the callers then treat as "Emacs is gone".
    """
    global epc_client

    if epc_client is None:
        try:
            epc_client = EPCClient(("127.0.0.1", emacs_server_port), log_traceback=True)
        except ConnectionRefusedError:
            traceback.print_exc()


def close_epc_client() -> None:
    """Close the connection to Emacs if it was ever opened."""
    global epc_client

    if epc_client is not None:
        epc_client.close()


def convert_arg_to_str(arg: Any) -> Any:
    """Convert ARG to the shape the Emacs side understands.

    Booleans become the strings ``TRUE`` or ``FALSE``; lists become a
    parenthesized, space separated string so that Emacs can split them back
    into a list; everything else is passed through unchanged.
    """
    if type(arg) is str:
        return arg
    elif type(arg) is bool:
        arg = str(arg).upper()
    elif type(arg) is list:
        new_arg = ""
        for a in arg:
            new_arg = new_arg + " " + str(convert_arg_to_str(a))
        arg = "(" + new_arg[1:] + ")"
    return arg


def string_to_base64(text: Any) -> str:
    """Return TEXT as Base64 of its UTF-8 representation."""
    return str(base64.b64encode(str(text).encode("utf-8")), "utf-8")


def eval_in_emacs(method_name: str, args: List[Any]) -> None:
    """Call the Emacs function named METHOD_NAME with the values in ARGS.

    ARGS is a list of arguments; each one is converted by
    `convert_arg_to_str' and then encoded by `string_to_base64'.  The call is
    asynchronous: this function returns before Emacs has run the function.
    """
    global epc_client

    if epc_client is None:
        print("Please call init_epc_client first before callling eval_in_emacs.")
    else:
        args = list(map(convert_arg_to_str, args))
        args = list(map(string_to_base64, args))

        args.insert(0, method_name)

        epc_client.call("eval-in-emacs", args)


def convert_emacs_bool(symbol_value: Any, symbol_is_boolean: str) -> Any:
    """Return SYMBOL_VALUE as the Python value it represents.

    SYMBOL_IS_BOOLEAN is the string that Emacs sends with every variable read;
    it is ``"t"`` when the Lisp value is a boolean, and any other value is
    returned unchanged.
    """
    if symbol_is_boolean == "t":
        return symbol_value is True
    else:
        return symbol_value


def get_emacs_vars(args: List[str]) -> List[Any]:
    """Return the values of the Emacs variables named in ARGS.

    A variable that Emacs answers with an empty list becomes ``False``, which
    is the value the rest of the Python side expects for an unset option.
    """
    global epc_client

    return list(
        map(
            lambda result: convert_emacs_bool(result[0], result[1]) if result != [] else False,
            epc_client.call_sync("get-emacs-vars", args),
        )
    )


def get_emacs_var(var_name: str) -> Any:
    """Return the value of the Emacs variable named VAR_NAME."""
    global epc_client

    (symbol_value, symbol_is_boolean) = epc_client.call_sync("get-emacs-var", [var_name])

    return convert_emacs_bool(symbol_value, symbol_is_boolean)


def get_emacs_func_result(method_name: str, args: List[Any]) -> Any:
    """Call the Emacs function METHOD_NAME with ARGS and return its result.

    Unlike `eval_in_emacs', this waits for Emacs to finish, so it must not be
    called from inside a Qt signal handler that Emacs is itself waiting on.
    The empty list that EPC uses for nil is turned into ``False``.
    """
    global epc_client

    if epc_client is None:
        print("Please call init_epc_client first before callling eval_in_emacs.")
    else:
        args = list(map(convert_arg_to_str, args))
        args = list(map(string_to_base64, args))

        args.insert(0, method_name)

        result = epc_client.call_sync("eval-in-emacs", args)
        return result if result != [] else False


def get_emacs_config_dir() -> str:
    """Return the configuration directory of popweb, creating it if needed.

    The path comes from the Emacs option `popweb-config-location' and is
    cached after the first read.  The returned path ends with a separator, so
    it can be joined with a relative name directly.
    """
    global emacs_config_dir

    if emacs_config_dir == "":
        emacs_config_dir = os.path.join(os.path.expanduser(get_emacs_var("popweb-config-location")), "")

    if not os.path.exists(emacs_config_dir):
        os.makedirs(emacs_config_dir)

    return emacs_config_dir
