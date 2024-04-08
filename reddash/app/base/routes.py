import typing  # isort:skip

import base64
import datetime
from copy import deepcopy

from reddash.app.app import app

import wtforms
from babel import Locale as BabelLocale
from babel import UnknownLocaleError
from django.utils.http import url_has_allowed_host_and_scheme
from flask import (
    abort,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)  # NOQA
from flask.helpers import send_from_directory
from flask_babel import _
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from markupsafe import Markup

from ..utils import AVAILABLE_COLORS, User, get_result, humanize_timedelta
from . import blueprint

current_user: User
from ..pagination import Pagination

# <--------- Index ---------->


@app.site_mapper.include()
@blueprint.route("/index")
@blueprint.route("/")
async def index():
    return render_template("pages/index.html")


@blueprint.route("/setcolor", methods=("POST",))
async def set_color():
    resp = make_response(jsonify({"status": 1}))
    color = request.json.get("color")
    if color is not None and color != app.data["ui"]["meta"]["default_color"]:
        resp.set_cookie(
            key="color",
            value=color,
            expires=datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=365),
        )
    else:
        resp.delete_cookie("color")
    return resp


@blueprint.route("/setbackgroundtheme", methods=("POST",))
async def set_background_theme():
    resp = make_response(jsonify({"status": 1}))
    background_theme = request.json.get("background_theme")
    if (
        background_theme is not None
        and background_theme != app.data["ui"]["meta"]["default_background_theme"]
    ):
        resp.set_cookie(
            key="background_theme",
            value=background_theme,
            expires=datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=365),
        )
    else:
        resp.delete_cookie("background_theme")
    return resp


@blueprint.route("/setsidebartheme", methods=("POST",))
async def set_sidebar_theme():
    resp = make_response(jsonify({"status": 1}))
    sidebar_theme = request.json.get("sidebar_theme")
    if (
        sidebar_theme is not None
        and sidebar_theme != app.data["ui"]["meta"]["default_sidebar_theme"]
    ):
        resp.set_cookie(
            key="sidebar_theme",
            value=sidebar_theme,
            expires=datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=365),
        )
    else:
        resp.delete_cookie("sidebar_theme")
    return resp


@blueprint.route("/sitemap.xml")
async def sitemap():
    return app.site_mapper.generate()


@blueprint.route("/robots.txt")
async def robots():
    return app.send_static_file("assets/robots.txt")


# For CertBot, to allow creating a SSL certificate.
app.add_url_rule(
    f"/.well-known/<path:filename>",
    endpoint=".well-known",
    host=None,
    view_func=lambda **kw: send_from_directory(".well-known", path=kw["filename"]),
)


@blueprint.route("/credits")
async def credits():
    return render_template("pages/credits.html")


# <---------- Base Pages ---------->


@app.site_mapper.include()
@blueprint.route("/commands/<cog>")
@blueprint.route("/commands")
async def commands(cog: typing.Optional[str] = None):
    cogs = {}
    commands = deepcopy(app.variables["commands"])
    len_cogs = 0
    len_commands = 0
    for _cog, cog_data in commands.items():
        len_cogs += 1
        _cog_data = cog_data.copy()
        _cog_data["commands"] = []
        for command in cog_data["commands"]:
            if command["privilege_level"] == "BOT_OWNER" and not (
                current_user.is_authenticated and current_user.is_owner
            ):
                continue
            len_commands += 1
            command_data = command.copy()

            def check_subs(subs):
                _subs = []
                for sub in subs:
                    if sub["privilege_level"] == "BOT_OWNER" and not (
                        current_user.is_authenticated and current_user.is_owner
                    ):
                        continue
                    nonlocal len_commands
                    len_commands += 1
                    if sub["subs"]:
                        sub["subs"] = check_subs(sub["subs"])
                    _subs.append(sub)
                return _subs

            command_data["subs"] = check_subs(command["subs"])
            _cog_data["commands"].append(command_data)
        if not _cog_data["commands"]:
            continue
        cogs[_cog] = _cog_data
    prefixes = app.variables["bot"]["prefixes"]

    return render_template(
        "pages/commands.html",
        cogs=cogs,
        prefixes=prefixes,
        len_cogs=len_cogs,
        len_commands=len_commands,
        tab_name=None if cog is None or cog not in cogs else cog,
        hidden=True if request.args.get("hidden") in ("True", "true") else False,
        filter_param=request.args.get("query"),
    )


@blueprint.route("/dashboard")
@login_required
async def dashboard():
    requeststr = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "DASHBOARDRPC__GET_USER_GUILDS",
        "params": [
            current_user.id,
            request.args.get("per_page"),
            request.args.get("page"),
            request.args.get("query"),
            request.args.get("filter"),
        ],
    }
    with app.lock:
        result = await get_result(app, requeststr)

    guilds = Pagination(result["guilds"])
    guilds.total = result["total"]
    guilds.per_page = result["per_page"]
    guilds.pages = result["pages"]
    guilds.page = result["page"]

    redirecting_to: str = (
        request.args.get("next") if not app.config["USE_SESSION_FOR_NEXT"] else session.get("next")
    ) or url_for("base_blueprint.dashboard_guild", guild_id="GUILD_ID")
    # `url_has_allowed_host_and_scheme` should check if the url is safe for redirects, meaning it matches the request host.
    if not url_has_allowed_host_and_scheme(redirecting_to, request.host):
        return abort(400)

    return render_template(
        "pages/dashboard.html",
        guilds=guilds,
        redirecting_to=redirecting_to,
        query=request.args.get("query"),
        filter=request.args.get("filter"),
    )


class LeaveGuildForm(FlaskForm):
    def __init__(self) -> None:
        super().__init__(prefix="leave_guild_form_")

    submit: wtforms.SubmitField = wtforms.SubmitField(_("Leave Guild"))


async def get_guild(guild_id: int):
    requeststr = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "DASHBOARDRPC__GET_GUILD",
        "params": [current_user.id, guild_id],
    }
    with app.lock:
        guild = await get_result(app, requeststr)
    if guild["status"] == 1:
        return abort(404, description=_("Guild not found or missing access to it."))
    guild["created_at"] = datetime.datetime.fromtimestamp(
        guild["created_at"], tz=datetime.timezone.utc
    )
    if guild["joined_at"] is not None:
        guild["joined_at"] = datetime.datetime.fromtimestamp(
            guild["joined_at"], tz=datetime.timezone.utc
        )

    if current_user.id in app.variables["bot"]["owner_ids"]:
        leave_guild_form: LeaveGuildForm = LeaveGuildForm()
        if leave_guild_form.validate_on_submit():
            requeststr = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "DASHBOARDRPC__LEAVE_GUILD",
                "params": [current_user.id, guild_id],
            }
            result = await get_result(app, requeststr)
            if result["status"] == 0:
                flash(_("Successfully left the guild."), category="success")
                return redirect(url_for("base_blueprint.dashboard"))
            else:
                flash(_("Failed to leave the guild."), category="danger")
                return redirect(request.url)
    else:
        leave_guild_form = None

    return {"guild": guild, "leave_guild_form": leave_guild_form}


class PrefixesCheck:
    def __call__(self, form: FlaskForm, field: wtforms.Field) -> None:
        if field.data == field.default:
            return
        for prefix in field.data.split(";;;;;"):
            if (
                not app.variables["constants"]["MIN_PREFIX_LENGTH"]
                <= len(prefix)
                <= app.variables["constants"]["MAX_PREFIX_LENGTH"]
            ):
                raise wtforms.validators.ValidationError(
                    _(
                        "Prefixes must be between %(min)s and %(max)s characters long.",
                        min=app.variables["constants"]["MIN_PREFIX_LENGTH"],
                        max=app.variables["constants"]["MAX_PREFIX_LENGTH"],
                    )
                )
            if prefix.startswith("/"):
                raise wtforms.validators.ValidationError(
                    _(
                        "Prefixes cannot start with `/`, as it conflicts with Discord's slash commands."
                    )
                )


class BabelCheck:
    def __init__(self, check_reset: bool = False) -> None:
        self.check_reset: bool = check_reset

    def __call__(self, form: FlaskForm, field: wtforms.Field) -> None:
        if field.data == field.default:
            return
        if self.check_reset and (not field.data or field.data.lower() in ("reset", "default")):
            field.data = None
            return
        try:
            locale = BabelLocale.parse(field.data, sep="-")
        except (ValueError, UnknownLocaleError):
            raise wtforms.validators.ValidationError(
                _("Invalid language code. Use format: `en-US`.")
            )
        if locale.territory is None:
            raise wtforms.validators.ValidationError(
                _("Invalid format - language code has to include country code, e.g. `en-US`.")
            )
        field.data = f"{locale.language}-{locale.territory}"


class GuildSettingsForm(FlaskForm):
    def __init__(self, guild: typing.Dict[str, typing.Any]) -> None:
        super().__init__(prefix="guild_settings_form_")
        if not guild["settings"]["edit_permission"]:
            for field in self:
                field.render_kw = {"disabled": True}
        self.bot_nickname.default = guild["settings"]["bot_nickname"]
        self.prefixes.default = ";;;;;".join(guild["settings"]["prefixes"])
        self.admin_roles.choices = [
            (str(role["id"]), f"{role['name']} ({role['id']})") for role in guild["roles"][1:]
        ]
        self.admin_roles.default = [str(role["id"]) for role in guild["settings"]["admin_roles"]]
        self.mod_roles.choices = [
            (str(role["id"]), f"{role['name']} ({role['id']})") for role in guild["roles"][1:]
        ]
        self.mod_roles.default = [str(role["id"]) for role in guild["settings"]["mod_roles"]]
        self.ignored.default = guild["settings"]["ignored"]
        available_commands = []
        all_commands = deepcopy(app.variables["commands"])
        for cog_data in all_commands.values():
            for command in cog_data["commands"]:
                if command["privilege_level"] == "BOT_OWNER" or command["name"] == "command":
                    continue
                available_commands.append((command["name"], command["name"]))

                def check_subs(subs):
                    _subs = []
                    for sub in subs:
                        if sub["privilege_level"] == "BOT_OWNER":
                            continue
                        available_commands.append((sub["name"], sub["name"]))
                        if sub["subs"]:
                            check_subs(sub["subs"])
                    return _subs

                check_subs(command["subs"])
        self.disabled_commands.choices = sorted(available_commands)
        self.disabled_commands.default = guild["settings"]["disabled_commands"].copy()
        self.embeds.default = guild["settings"]["embeds"]
        self.use_bot_color.default = guild["settings"]["use_bot_color"]
        self.fuzzy.default = guild["settings"]["fuzzy"]
        self.delete_delay.default = guild["settings"]["delete_delay"]
        self.locale.default = guild["settings"]["locale"]
        self.regional_format.default = guild["settings"]["regional_format"]

    bot_nickname: wtforms.StringField = wtforms.StringField(
        _("Bot Nickname"), validators=[wtforms.validators.Length(max=32)]
    )
    prefixes: wtforms.StringField = wtforms.StringField(
        _("Prefixes"), validators=[PrefixesCheck()]
    )
    admin_roles: wtforms.SelectMultipleField = wtforms.SelectMultipleField(
        _("Admin Roles"), choices=[]
    )
    mod_roles: wtforms.SelectMultipleField = wtforms.SelectMultipleField(
        _("Mod Roles"), choices=[]
    )
    ignored: wtforms.BooleanField = wtforms.BooleanField(_("Ignore commands in this guild."))
    disabled_commands: wtforms.SelectMultipleField = wtforms.SelectMultipleField(
        _("Disabled Commands"), choices=[]
    )
    embeds: wtforms.BooleanField = wtforms.BooleanField(_("Use embeds in responses."))
    use_bot_color: wtforms.BooleanField = wtforms.BooleanField(_("Use bot color in embeds."))
    fuzzy: wtforms.BooleanField = wtforms.BooleanField(_("Use fuzzy command search."))
    delete_delay: wtforms.IntegerField = wtforms.IntegerField(
        _("Delay before deleting invokation messages (-1 to disable)"),
        validators=[
            wtforms.validators.DataRequired(),
            wtforms.validators.NumberRange(min=-1, max=60),
        ],
    )
    locale: wtforms.StringField = wtforms.StringField(
        _("Locale"), validators=[wtforms.validators.DataRequired(), BabelCheck(check_reset=True)]
    )
    regional_format: wtforms.StringField = wtforms.StringField(
        _("Region"), validators=[wtforms.validators.Optional(), BabelCheck(check_reset=True)]
    )
    submit: wtforms.SubmitField = wtforms.SubmitField(_("Save Modifications"))


@blueprint.route("/dashboard/<guild_id>/<page>/<third_party>", methods=("GET", "POST"))
@blueprint.route("/dashboard/<guild_id>/<page>", methods=("GET", "POST"))
@blueprint.route("/dashboard/<guild_id>", methods=("GET", "POST"))
@login_required
async def dashboard_guild(
    guild_id: str,
    page: typing.Optional[typing.Literal["overview", "settings", "third-parties"]] = None,
    third_party: typing.Optional[str] = None,
):
    try:
        guild_id = int(guild_id)
    except ValueError:
        return abort(404, description=_("Guild ID must be an integer."))
    return_guild = await get_guild(guild_id)
    if return_guild["guild"]["status"] == 1:
        return return_guild["guild"]

    guild_settings_form: GuildSettingsForm = GuildSettingsForm(guild=return_guild["guild"])
    if (
        guild_settings_form.validate_on_submit()
        and return_guild["guild"]["settings"]["edit_permission"]
    ):
        requeststr = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "DASHBOARDRPC__SET_GUILD_SETTINGS",
            "params": [
                current_user.id,
                guild_id,
                {
                    "bot_nickname": guild_settings_form.bot_nickname.data.strip() or None,
                    "prefixes": guild_settings_form.prefixes.data.split(";;;;;"),
                    "admin_roles": guild_settings_form.admin_roles.data,
                    "mod_roles": guild_settings_form.mod_roles.data,
                    "ignored": guild_settings_form.ignored.data,
                    "disabled_commands": guild_settings_form.disabled_commands.data,
                    "embeds": guild_settings_form.embeds.data,
                    "use_bot_color": guild_settings_form.use_bot_color.data,
                    "fuzzy": guild_settings_form.fuzzy.data,
                    "delete_delay": guild_settings_form.delete_delay.data,
                    "locale": guild_settings_form.locale.data,
                    "regional_format": guild_settings_form.regional_format.data,
                },
            ],
        }
        result = await get_result(app, requeststr)
        if result["status"] == 0:
            if result.get("change_nickname_error"):
                flash(
                    _(
                        "Failed to change the bot's nickname. Make sure the bot has the required permissions."
                    ),
                    category="danger",
                )
            flash(_("Successfully saved the modifications."), category="success")
        else:
            flash(_("Failed to save the modifications."), category="danger")
        return redirect(request.url)
    elif guild_settings_form.submit.data and guild_settings_form.errors:
        for field_name, error_messages in guild_settings_form.errors.items():
            flash(f"{field_name}: {' '.join(error_messages)}", category="warning")

    return_third_parties = await get_third_parties(guild_id=return_guild["guild"]["id"])

    return render_template(
        "pages/dashboard_guild.html",
        **return_guild,
        page=page
        if page is not None and page in ("overview", "settings", "third-parties")
        else "overview",
        guild_settings_form=guild_settings_form,
        **return_third_parties,
        tab_name=None
        if third_party is None or third_party not in return_third_parties["third_parties"]
        else third_party,
    )


async def get_third_parties(guild_id: typing.Optional[str] = None):
    _third_parties = {
        third_party: pages.copy() for third_party, pages in app.variables["third_parties"].items()
    }
    cogs_data = app.variables["commands"]
    infos = {third_party: {} for third_party in _third_parties}
    third_parties = {}
    for third_party, pages in sorted(_third_parties.items()):
        if third_party in app.data["disabled_third_parties"]:
            continue
        if not pages:
            continue
        if all(page["hidden"] for page in pages.values()):
            continue
        real_cog_name = third_party  # _third_parties[third_party][list(pages)[0]]["real_cog_name"]
        if real_cog_name in cogs_data:
            infos[third_party]["description"] = cogs_data[real_cog_name]["description"]
            infos[third_party]["author"] = cogs_data[real_cog_name]["author"]
            infos[third_party]["repo"] = cogs_data[real_cog_name]["repo"]
        else:
            infos[third_party]["description"] = ""
            infos[third_party]["author"] = "Unknown"
            infos[third_party]["repo"] = "Unknown"
        third_parties[third_party] = {}
        if (
            "null" in _third_parties[third_party]
            and not _third_parties[third_party]["null"]["hidden"]
        ):
            third_parties[third_party]["Main Page"] = _third_parties[third_party].pop("null")
            third_parties[third_party]["Main Page"]["url"] = url_for(
                "third_parties_blueprint.third_party",
                name=third_party,
                page=None,
                guild_id=guild_id,
            )
        for page in sorted(pages):
            if not pages[page]["hidden"]:
                third_parties[third_party][page] = pages[page]
                third_parties[third_party][page]["url"] = url_for(
                    "third_parties_blueprint.third_party",
                    name=third_party,
                    page=page,
                    guild_id=guild_id,
                )
    return {"third_parties": third_parties, "third_parties_infos": infos}


class DashboardActionsForm(FlaskForm):
    def __init__(self) -> None:
        super().__init__(prefix="dashboard_actions_form_")

    lock: wtforms.SubmitField = wtforms.SubmitField(_("Lock Dashboard"))
    refresh_sessions: wtforms.SubmitField = wtforms.SubmitField(_("Refresh Sessions"))


class MarkdownTextAreaField(wtforms.TextAreaField):
    def __call__(
        self,
        auto_save: bool = False,
        max_height: bool = False,
        disable_toolbar: bool = False,
        **kwargs,
    ) -> Markup:
        if "class" not in kwargs:
            kwargs["class"] = "markdown-text-area-field"
        else:
            kwargs["class"] += " markdown-text-area-field"
        if auto_save:
            kwargs["class"] += " markdown-text-area-field-autosave"
        if max_height:
            kwargs["class"] += " markdown-text-area-field-max-height"
        if disable_toolbar:
            kwargs["class"] += " markdown-text-area-field-toolbar-disabled"
        return super().__call__(**kwargs)


class DiscordProfileForm(FlaskForm):
    def __init__(self) -> None:
        super().__init__(prefix="bot_profile_form_")
        self.username.default = app.variables["bot"]["name"]
        self.description.default = app.variables["bot"]["profile_description"]

    avatar: FileField = FileField(_("Avatar"))
    avatar_choice: wtforms.HiddenField = wtforms.HiddenField(_("Avatar choice"), default="keep")
    username: wtforms.StringField = wtforms.StringField(
        _("Username"), validators=[wtforms.validators.Length(max=32)]
    )
    description: MarkdownTextAreaField = MarkdownTextAreaField(
        _("Description"), validators=[wtforms.validators.Length(max=1024)]
    )
    submit: wtforms.SubmitField = wtforms.SubmitField(_("Save Modifications"))


class DashboardSettingsForm(FlaskForm):
    def __init__(self, settings: typing.Dict[str, typing.Any]) -> None:
        super().__init__(prefix="dashboard_settings_form_")
        self.title.default = settings["title"]
        self.icon.default = settings["icon"]
        self.description.default = settings["description"]
        self.support_server.default = settings["support_server"]
        self.default_color.default = settings["default_color"]
        self.default_background_theme.default = settings["default_background_theme"]
        self.default_sidebar_theme.default = settings["default_sidebar_theme"]
        self.disabled_third_parties.choices = [
            (third_party, third_party) for third_party in app.variables["third_parties"]
        ]
        self.disabled_third_parties.default = settings["disabled_third_parties"].copy()

    title: wtforms.StringField = wtforms.StringField(_("Title"))
    icon: wtforms.StringField = wtforms.StringField(_("Icon"))
    description: MarkdownTextAreaField = MarkdownTextAreaField(_("Description"))
    support_server: wtforms.StringField = wtforms.StringField(_("Support Server"))
    default_color: wtforms.SelectField = wtforms.SelectField(
        _("Default Color"),
        choices=[(color, color.capitalize()) for color in AVAILABLE_COLORS],
        validators=[wtforms.validators.DataRequired()],
    )
    default_background_theme: wtforms.SelectField = wtforms.SelectField(
        _("Default Background Theme"),
        choices=[("light", "Light"), ("dark", "Dark")],
        validators=[wtforms.validators.DataRequired()],
    )
    default_sidebar_theme: wtforms.SelectField = wtforms.SelectField(
        _("Default Sidebar Theme"),
        choices=[("light", "Light"), ("dark", "Dark")],
        validators=[wtforms.validators.DataRequired()],
    )
    disabled_third_parties: wtforms.SelectMultipleField = wtforms.SelectMultipleField(
        _("Disabled Third Parties"), choices=[]
    )
    submit: wtforms.SubmitField = wtforms.SubmitField(_("Save Modifications"))


class BotSettingsForm(FlaskForm):
    def __init__(self, settings: typing.Dict[str, typing.Any]) -> None:
        super().__init__(prefix="bot_settings_form_")
        self.prefixes.default = ";;;;;".join(settings["prefixes"])
        self.invoke_error_msg.default = settings["invoke_error_msg"]
        available_commands = []
        all_commands = deepcopy(app.variables["commands"])
        for cog_data in all_commands.values():
            for command in cog_data["commands"]:
                if command["privilege_level"] == "BOT_OWNER" or command["name"] == "command":
                    continue
                available_commands.append((command["name"], command["name"]))

                def check_subs(subs):
                    _subs = []
                    for sub in subs:
                        if sub["privilege_level"] == "BOT_OWNER":
                            continue
                        available_commands.append((sub["name"], sub["name"]))
                        if sub["subs"]:
                            check_subs(sub["subs"])
                    return _subs

                check_subs(command["subs"])
        self.disabled_commands.choices = sorted(available_commands)
        self.disabled_commands.default = settings["disabled_commands"].copy()
        self.disabled_command_msg.default = settings["disabled_command_msg"]
        self.description.default = settings["description"]
        self.custom_info.default = settings["custom_info"]
        self.embeds.default = settings["embeds"]
        self.color.default = settings["color"]
        self.fuzzy.default = settings["fuzzy"]
        self.use_buttons.default = settings["use_buttons"]
        self.invite_public.default = settings["invite_public"]
        self.invite_commands_scope.default = settings["invite_commands_scope"]
        self.invite_perms.validators.append(wtforms.validators.NumberRange(min=0, max=app.variables["constants"]["MAX_DISCORD_PERMISSIONS_VALUE"]))
        self.invite_perms.default = settings["invite_perms"]
        self.locale.default = settings["locale"]
        self.regional_format.default = settings["regional_format"]

    prefixes: wtforms.StringField = wtforms.StringField(
        _("Prefixes"), validators=[wtforms.validators.DataRequired(), PrefixesCheck()]
    )
    invoke_error_msg: wtforms.StringField = wtforms.StringField(
        _("Invoke Error Message"), validators=[wtforms.validators.Length(max=1000)]
    )
    disabled_commands: wtforms.SelectMultipleField = wtforms.SelectMultipleField(
        _("Disabled Commands"), choices=[]
    )
    disabled_command_msg: wtforms.StringField = wtforms.StringField(_("Disabled Command Message"))
    description: wtforms.StringField = wtforms.StringField(
        _("Description"), validators=[wtforms.validators.Length(max=250)]
    )
    custom_info: MarkdownTextAreaField = MarkdownTextAreaField(
        _("Custom Info"), validators=[wtforms.validators.Length(max=1024)]
    )
    embeds: wtforms.BooleanField = wtforms.BooleanField(_("Use Embeds"))
    color: wtforms.ColorField = wtforms.ColorField(_("Color"))
    fuzzy: wtforms.BooleanField = wtforms.BooleanField(_("Use Fuzzy"))
    use_buttons: wtforms.BooleanField = wtforms.BooleanField(_("Use Buttons"))
    invite_public: wtforms.BooleanField = wtforms.BooleanField(_("Invite Public"))
    invite_commands_scope: wtforms.BooleanField = wtforms.BooleanField(_("Invite Commands Scope"))
    invite_perms: wtforms.IntegerField = wtforms.IntegerField(
        _("Invite Permissions (0 for nothing)"),
        validators=[
            wtforms.validators.DataRequired(),
        ],
    )
    locale: wtforms.StringField = wtforms.StringField(
        _("Locale"), validators=[wtforms.validators.DataRequired(), BabelCheck()]
    )
    regional_format: wtforms.StringField = wtforms.StringField(
        _("Regional Format"),
        validators=[wtforms.validators.Optional(), BabelCheck(check_reset=True)],
    )
    submit: wtforms.SubmitField = wtforms.SubmitField(_("Save Modifications"))


@blueprint.route("/admin/<page>", methods=("GET", "POST"))
@blueprint.route("/admin", methods=("GET", "POST"))
@login_required
async def admin(
    page: typing.Optional[typing.Literal["overview", "dashboard-settings", "bot-settings"]] = None
):
    if not current_user.is_authenticated or not current_user.is_owner:
        return abort(403, description=_("You're not a bot owner!"))

    uptime_str = humanize_timedelta(
        timedelta=datetime.datetime.now(tz=datetime.timezone.utc) - app.config["LAUNCH"]
    )
    connection_str = humanize_timedelta(
        timedelta=datetime.datetime.now(tz=datetime.timezone.utc) - app.config["LAST_RPC_EVENT"]
    )

    bot_profile_form: DiscordProfileForm = DiscordProfileForm()
    if bot_profile_form.validate_on_submit():
        requeststr = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "DASHBOARDRPC__SET_BOT_PROFILE",
            "params": [
                current_user.id,
                {
                    "avatar": base64.b64encode(bot_profile_form.avatar.data)
                    if bot_profile_form.avatar.data is not None
                    else bot_profile_form.avatar_choice.data,
                    "name": bot_profile_form.username.data.strip() or None,
                    "profile_description": bot_profile_form.description.data.strip() or None,
                },
            ],
        }
        result = await get_result(app, requeststr)
        if result["status"] == 0:
            flash(_("Successfully saved the modifications."), category="success")
        else:
            if "error" in result:
                flash(result["error"], category="danger")
            flash(_("Failed to save the modifications."), category="danger")
        return redirect(request.url)
    elif bot_profile_form.submit.data and bot_profile_form.errors:
        for field_name, error_messages in bot_profile_form.errors.items():
            flash(f"{field_name}: {' '.join(error_messages)}", category="warning")

    dashboard_actions_form: DashboardActionsForm = DashboardActionsForm()
    if app.locked:
        dashboard_actions_form.lock.label.text = _("Unlock Dashboard")
    if dashboard_actions_form.validate_on_submit():
        if dashboard_actions_form.lock.data:
            app.locked = not app.locked
            if app.locked:
                flash(_("Dashboard locked."), category="success")
            else:
                flash(_("Dashboard unlocked."), category="success")
        elif dashboard_actions_form.refresh_sessions.data:
            User.USERS.clear()
            flash(_("Users sessions refreshed."), category="success")
        return redirect(request.url)
    elif dashboard_actions_form.lock.data and dashboard_actions_form.errors:
        for field_name, error_messages in dashboard_actions_form.errors.items():
            flash(f"{field_name}: {' '.join(error_messages)}", category="warning")

    requeststr = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "DASHBOARDRPC__GET_DASHBOARD_SETTINGS",
        "params": [current_user.id],
    }
    with app.lock:
        dashboard_settings = await get_result(app, requeststr)
    dashboard_settings_form: DashboardSettingsForm = DashboardSettingsForm(
        settings=dashboard_settings
    )
    if dashboard_settings_form.validate_on_submit():
        new_dashboard_settings = {
            "title": dashboard_settings_form.title.data.strip() or None,
            "icon": dashboard_settings_form.icon.data.strip() or None,
            "description": dashboard_settings_form.description.data.strip() or None,
            "support_server": dashboard_settings_form.support_server.data.strip() or None,
            "default_color": dashboard_settings_form.default_color.data,
            "default_background_theme": dashboard_settings_form.default_background_theme.data,
            "default_sidebar_theme": dashboard_settings_form.default_sidebar_theme.data,
            "disabled_third_parties": dashboard_settings_form.disabled_third_parties.data,
        }
        requeststr = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "DASHBOARDRPC__SET_DASHBOARD_SETTINGS",
            "params": [
                current_user.id,
                new_dashboard_settings,
            ],
        }
        result = await get_result(app, requeststr)
        if result["status"] == 0:
            app.data["disabled_third_parties"] = new_dashboard_settings.pop(
                "disabled_third_parties"
            )
            app.data["ui"]["meta"].update(**new_dashboard_settings)
            flash(_("Successfully saved the modifications."), category="success")
        else:
            flash(_("Failed to save the modifications."), category="danger")
        return redirect(request.url)
    elif dashboard_settings_form.submit.data and dashboard_settings_form.errors:
        for field_name, error_messages in dashboard_settings_form.errors.items():
            flash(f"{field_name}: {' '.join(error_messages)}", category="warning")

    requeststr = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "DASHBOARDRPC__GET_BOT_SETTINGS",
        "params": [current_user.id],
    }
    with app.lock:
        bot_settings = await get_result(app, requeststr)
    bot_settings_form: BotSettingsForm = BotSettingsForm(settings=bot_settings)
    if bot_settings_form.validate_on_submit():
        requeststr = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "DASHBOARDRPC__SET_BOT_SETTINGS",
            "params": [
                current_user.id,
                {
                    "prefixes": bot_settings_form.prefixes.data,
                    "invoke_error_msg": bot_settings_form.invoke_error_msg.data.strip() or None,
                    "disabled_commands": bot_settings_form.disabled_commands.data,
                    "disabled_command_msg": bot_settings_form.disabled_command_msg.data.strip()
                    or None,
                    "description": bot_settings_form.description.data.strip() or None,
                    "custom_info": bot_settings_form.custom_info.data.strip() or None,
                    "embeds": bot_settings_form.embeds.data,
                    "color": bot_settings_form.color.data.strip() or None,
                    "fuzzy": bot_settings_form.fuzzy.data,
                    "use_buttons": bot_settings_form.use_buttons.data,
                    "invite_public": bot_settings_form.invite_public.data,
                    "invite_commands_scope": bot_settings_form.invite_commands_scope.data,
                    "invite_perms": bot_settings_form.invite_perms.data,
                    "locale": bot_settings_form.locale.data,
                    "regional_format": bot_settings_form.regional_format.data,
                },
            ],
        }
        result = await get_result(app, requeststr)
        if result["status"] == 0:
            flash(_("Successfully saved the modifications."), category="success")
        else:
            flash(_("Failed to save the modifications."), category="danger")
        return redirect(request.url)
    elif bot_settings_form.submit.data and bot_settings_form.errors:
        for field_name, error_messages in bot_settings_form.errors.items():
            flash(f"{field_name}: {' '.join(error_messages)}", category="warning")

    return render_template(
        "pages/admin.html",
        page=page
        if page is not None and page in ("overview", "dashboard-settings", "bot-settings")
        else "overview",
        uptime_str=uptime_str,
        connection_str=connection_str,
        bot_profile_form=bot_profile_form,
        dashboard_actions_form=dashboard_actions_form,
        dashboard_settings_form=dashboard_settings_form,
        bot_settings_form=bot_settings_form,
    )