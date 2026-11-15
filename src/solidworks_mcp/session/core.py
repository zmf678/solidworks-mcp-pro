"""Connection, document lifecycle, guarded calls and COM-thread helpers.

Part of the :class:`SolidWorksSession` mixin split. Every method here must
run on the COM worker thread (see :mod:`solidworks_mcp.com_worker`).
"""

import contextlib
import os
import re

import pythoncom

from .. import __version__, binding
from ..constants import (
    IMPORT_FORMATS,
    LENGTH_UNITS,
    SW_BODY_SOLID,
    SW_DELETE_ABSORBED,
    SW_DETAILING_NO_OPTION,
    SW_DOC_ASSEMBLY,
    SW_DOC_PART,
    SW_DONT_REBUILD_ACTIVE_DOC,
    SW_PREF_DEFAULT_TEMPLATE_ASSEMBLY,
    SW_PREF_DEFAULT_TEMPLATE_PART,
    SW_SAVE_AS_CURRENT_VERSION,
    SW_SAVE_AS_OPTIONS_SILENT,
    SW_TOGGLE_3D_INTERCONNECT,
    SW_TOGGLE_INPUT_DIM_VAL_ON_CREATE,
    SW_UNITS_LINEAR,
)
from ..errors import SolidWorksError
from ._constants import SessionConstants
from ._decorators import _reads_only


class CoreMixin:
    """Connection, document lifecycle, guarded calls and COM-thread helpers."""

    def __init__(self) -> None:
        self._sw = None  # early-bound ISldWorks
        self._mod = None  # generated wrapper module
        self._model = None  # current IModelDoc2
        self._quiet_depth = 0  # inside _quiet_ui
        self._reading = 0  # inside a tool that only reads (_reads_only)
        self._to_wake = []  # (document, [(object, property)]) to switch back on after it

    def _ensure(self):
        if self._sw is None:
            self.connect()
        return self._sw

    def connect(self) -> dict:
        """Attach to the running SolidWorks instance and configure it for automation."""
        self._sw = binding.connect()
        self._mod = binding.module()
        self._configure_for_automation()
        return self.get_status()

    def _configure_for_automation(self) -> None:
        # Suppress the modal "enter dimension value" popup so an unattended run
        # cannot deadlock waiting for a click. Best-effort.
        try:
            self._sw.SetUserPreferenceToggle(SW_TOGGLE_INPUT_DIM_VAL_ON_CREATE, False)
        except pythoncom.com_error:
            pass

    def _revision(self):
        # On the early-bound wrapper RevisionNumber may come back as a property
        # (string) or as a method, depending on how makepy generated it; handle
        # both. See Docs/PROGRESS.md.
        rev = self._sw.RevisionNumber
        return rev() if callable(rev) else rev

    def _require_model(self):
        """The current document, made SolidWorks' active one first.

        Sketching in a document that is open but not active fails at the first
        relation ('refused a horizontal relation'); that happened after
        open_part returned a part that was already open behind another document,
        and would after any switch of window in SolidWorks itself.
        """
        if self._reading:
            # not activated, but kept still all the same: the guard against
            # SP4.0's random crash in slduiu.dll is the stilled view, not activation
            model = self._current_model()
            if self._quiet_depth:
                self._quiet(model)
            return model
        if self._model is None:
            raise SolidWorksError("No active document. Call 'new_part' or 'new_assembly' first.")
        title = self._model.GetTitle()
        active = binding.wrap(self._sw.ActiveDoc, self._mod.IModelDoc2)
        if active is None or active.GetTitle() != title:
            self._sw.ActivateDoc3(title, False, SW_DONT_REBUILD_ACTIVE_DOC, 0)
        if self._quiet_depth:
            self._quiet(self._model)
        if int(self._model.GetType()) == SW_DOC_ASSEMBLY and not self._model.IsEditingSelf():
            # left editing one of its parts (a double click in SolidWorks): the other
            # components show see-through and AddComponent5 returns None
            binding.wrap(self._model, self._mod.IAssemblyDoc).EditAssembly()
            if not self._model.IsEditingSelf():
                raise SolidWorksError(
                    f"'{title}' is editing one of its parts and would not go back to editing "
                    "the assembly; choose Edit Assembly in SolidWorks."
                )
        return self._model

    def _current_model(self):
        """The current document as it is, without making it SolidWorks' active one:
        enough to read it (features, dimensions, faces, mass properties)."""
        if self._model is None:
            raise SolidWorksError("No active document. Call 'new_part' or 'new_assembly' first.")
        return self._model

    @contextlib.contextmanager
    def _writing(self):
        """Within a read-only tool, a step that writes after all (the temporary
        sketch line measure_distance measures to): the document is made the
        active one and stilled first, as for every tool that writes."""
        reading, self._reading = self._reading, 0
        try:
            self._require_model()
            yield
        finally:
            self._reading = reading

    def _require_part(self):
        """The current document as an IPartDoc; raises if it is an assembly.

        Part tools would otherwise sketch into an assembly and fail much later
        with an opaque message, so the doc type is checked at the choke points
        every part builder passes through (_first_ref_plane / _solid_body).
        """
        model = self._require_model()
        if int(model.GetType()) != SW_DOC_PART:
            raise SolidWorksError(
                f"The current document '{model.GetTitle()}' is an assembly, not a part. "
                "Call 'new_part' or 'open_part', or use the assembly tools."
            )
        return binding.wrap(model, self._mod.IPartDoc)

    def _require_assembly(self):
        """The current document as an IAssemblyDoc; raises if it is a part."""
        model = self._require_model()
        if int(model.GetType()) != SW_DOC_ASSEMBLY:
            raise SolidWorksError(
                f"The current document '{model.GetTitle()}' is not an assembly. "
                "Call 'new_assembly' or 'open_assembly' first."
            )
        return binding.wrap(model, self._mod.IAssemblyDoc)

    def get_status(self) -> dict:
        sw = self._ensure()
        active = binding.wrap(sw.ActiveDoc, self._mod.IModelDoc2)
        active_title = active.GetTitle() if active is not None else None
        return {
            "ok": True,
            "connected": True,
            "server_version": __version__,
            "revision": self._revision(),
            "active_document": active_title,
            "current_part": self._model.GetTitle() if self._model is not None else None,
        }

    def describe_installation(self) -> dict:
        """What differs between SolidWorks installations: release, language,
        default templates and the part template's length unit.

        For the selftest. Opens a new part to read the unit and closes it again.
        """
        sw = self._ensure()
        templates = {}
        for kind, preference in (
            ("part", SW_PREF_DEFAULT_TEMPLATE_PART),
            ("assembly", SW_PREF_DEFAULT_TEMPLATE_ASSEMBLY),
        ):
            path = sw.GetUserPreferenceStringValue(preference)
            templates[f"{kind}_template"] = {"path": path, "found": bool(path) and os.path.isfile(path)}
        self.new_part()
        try:
            extension = binding.wrap(self._model.Extension, self._mod.IModelDocExtension)
            unit = extension.GetUserPreferenceInteger(SW_UNITS_LINEAR, SW_DETAILING_NO_OPTION)
        finally:
            self.close_part()
        return {
            "revision": self._revision(),
            "language": sw.GetCurrentLanguage(),
            "units": LENGTH_UNITS.get(unit, f"unit {unit}"),
            **templates,
        }

    def new_part(self) -> dict:
        """Create a new empty part; it becomes the current document."""
        sw = self._ensure()
        template = sw.GetUserPreferenceStringValue(SW_PREF_DEFAULT_TEMPLATE_PART)
        model = None
        if template and os.path.isfile(template):
            model = binding.wrap(sw.NewDocument(template, 0, 0, 0), self._mod.IModelDoc2)
        if model is None:
            # Fallback avoids a "template not found" modal dialog.
            model = binding.wrap(sw.NewPart(), self._mod.IModelDoc2)
        if model is None:
            raise SolidWorksError("Could not create a new part document (template and NewPart both failed).")
        self._model = model
        return {"ok": True, "title": model.GetTitle()}

    def close_part(self, save: bool = False) -> dict:
        """Close the current document (part or assembly). CloseDoc never prompts.

        Without a current document it closes SolidWorks' active one, but only
        when that has no unsaved changes: closing never asks, so they would be
        lost.
        """
        if save:
            raise SolidWorksError(
                "Saving on close is not supported yet; use 'save_part', 'save_assembly' or 'export' first."
            )
        if self._model is None:
            return self._close_active_document()
        title = self._require_model().GetTitle()
        self._sw.CloseDoc(title)
        self._model = None
        return {"ok": True, "closed": title}

    def _open_documents(self) -> list:
        return [binding.wrap(d, self._mod.IModelDoc2) for d in (self._ensure().GetDocuments() or ())]

    def _document_entry(self, document) -> dict:
        return {
            "title": document.GetTitle(),
            "path": document.GetPathName(),
            "type": self._DOC_TYPES.get(int(document.GetType()), "other"),
            "modified": bool(document.GetSaveFlag()),
            "visible": bool(document.Visible),
        }

    def list_documents(self) -> dict:
        """The documents open in SolidWorks: title, path (empty until saved),
        type, unsaved changes, and which one is current here and active there.
        Parts an open assembly loaded come along, not visible."""
        current = self._model.GetTitle() if self._model is not None else None
        active = binding.wrap(self._ensure().ActiveDoc, self._mod.IModelDoc2)
        active = active.GetTitle() if active is not None else None
        out = [
            {**self._document_entry(d), "current": d.GetTitle() == current, "active": d.GetTitle() == active}
            for d in self._open_documents()
        ]
        return {"ok": True, "count": len(out), "documents": out}

    def activate_document(self, title: str) -> dict:
        """Make an open document current again by its title (list_documents),
        also a new one that was never saved."""
        documents = self._open_documents()
        key = re.sub(r"\.(sldprt|sldasm|slddrw)$", "", str(title).strip(), flags=re.IGNORECASE).lower()
        matches = [d for d in documents if d.GetTitle() == title] or [
            d
            for d in documents
            if re.sub(r"\.(sldprt|sldasm|slddrw)$", "", d.GetTitle(), flags=re.IGNORECASE).lower() == key
        ]
        if len(matches) != 1:
            listed = ", ".join(d.GetTitle() for d in documents) or "none"
            raise SolidWorksError(f"No open document '{title}' (open: {listed}).")
        self._model = matches[0]
        self._require_model()  # SolidWorks' active document too
        return {"ok": True, "current": self._model.GetTitle(), **self._document_entry(self._model)}

    def _close_active_document(self) -> dict:
        active = binding.wrap(self._ensure().ActiveDoc, self._mod.IModelDoc2)
        if active is None:
            raise SolidWorksError("No document is open.")
        title = active.GetTitle()
        if active.GetSaveFlag():
            raise SolidWorksError(
                f"There is no current document, and SolidWorks' active document '{title}' has unsaved "
                "changes, so it stays open. Save it in SolidWorks, or open it with open_part or "
                "open_assembly to work on it."
            )
        self._sw.CloseDoc(title)
        return {"ok": True, "closed": title}

    def _write_via_saveas3(self, abs_path: str, document=None) -> None:
        """SaveAs3 `document` (the current one by default) to abs_path, silent,
        and verify the file was actually (re)written.

        Checks the modification time advanced, so a silent SaveAs3 failure over a
        pre-existing file (locked/read-only target) is not reported as success.
        """
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        before = os.path.getmtime(abs_path) if os.path.isfile(abs_path) else None
        result = (document or self._model).SaveAs3(abs_path, SW_SAVE_AS_CURRENT_VERSION, SW_SAVE_AS_OPTIONS_SILENT)
        if not os.path.isfile(abs_path) or (before is not None and os.path.getmtime(abs_path) == before):
            raise SolidWorksError(
                f"Write failed: '{abs_path}' was not (re)written; SaveAs3 returned {result}. "
                "Is the file open or locked?"
            )

    def save_part(self, path: str) -> dict:
        """Save the current part to a native .sldprt file (silent)."""
        self._require_model()
        abs_path = os.path.abspath(path)
        if not abs_path.lower().endswith(".sldprt"):
            abs_path += ".sldprt"
        self._write_via_saveas3(abs_path)
        return {"ok": True, "path": abs_path, "bytes": os.path.getsize(abs_path)}

    def open_part(self, path: str, allow_large: bool = False) -> dict:
        """Open an existing .sldprt, or import a STEP, IGES or Parasolid file as a
        new part; it becomes the current part.

        An imported body has no history, but the tools work on it: holes and
        pockets on its faces, bosses, fillets. An import also returns its solid
        body count and mass properties, to see what came in and where it lies.
        A file over _IMPORT_LIMIT_MB is refused unless allow_large.
        """
        abs_path, imported = self._native_or_neutral(path, "sldprt", "a part", allow_large)
        sw = self._ensure()
        if imported:
            model = self._import_document(sw, abs_path, SW_DOC_PART)
            bodies = binding.wrap(model, self._mod.IPartDoc).GetBodies2(SW_BODY_SOLID, True) or ()
            if not bodies:
                sw.CloseDoc(model.GetTitle())
                raise SolidWorksError(
                    f"{os.path.basename(abs_path)} brought in no solid body (only surfaces?), "
                    "so there is nothing to build on."
                )
            self._model = model
            return {
                "ok": True,
                "title": model.GetTitle(),
                "path": abs_path,
                "imported": True,
                "solid_bodies": len(bodies),
                "mass_properties": self.get_mass_properties()["mass_properties"],
            }
        result = sw.OpenDoc6(abs_path, SW_DOC_PART, 0, "", 0, 0)
        doc = result[0] if isinstance(result, tuple) else result
        model = binding.wrap(doc, self._mod.IModelDoc2)
        if model is None:
            raise SolidWorksError(f"Could not open the part: {abs_path}")
        self._model = model
        return {"ok": True, "title": model.GetTitle(), "path": abs_path}

    @staticmethod
    def _native_or_neutral(path: str, native: str, kind: str, allow_large: bool = False) -> tuple:
        """(absolute path, whether it needs an import); other formats, and an
        import over _IMPORT_LIMIT_MB, are refused before SolidWorks is touched."""
        abs_path = os.path.abspath(path)
        extension = os.path.splitext(abs_path)[1].lower().lstrip(".")
        if extension != native and extension not in IMPORT_FORMATS:
            raise SolidWorksError(
                f"Cannot open a .{extension} file as {kind}: use .{native}, or import "
                f"{', '.join('.' + f for f in sorted(IMPORT_FORMATS))}."
            )
        if not os.path.isfile(abs_path):
            raise SolidWorksError(f"File not found: {abs_path}")
        size_mb = os.path.getsize(abs_path) / 2**20
        if extension != native and size_mb > SessionConstants._IMPORT_LIMIT_MB and not allow_large:
            raise SolidWorksError(
                f"{os.path.basename(abs_path)} is {size_mb:.0f} MB: an import that large can run past the 2 minutes "
                "a call may take, and SolidWorks keeps working on it (a 77 MB STEP did, with popups). Import it "
                "in SolidWorks by hand and save it as .sldprt/.sldasm, use a simplified model, or pass "
                "allow_large=True to try anyway."
            )
        return abs_path, extension != native

    def _import_document(self, sw, abs_path: str, doc_type: int):
        """Import a STEP/IGES/Parasolid file; a document of the other type is
        closed again (components and all) with the tool that does take it.

        An assembly is imported with 3D Interconnect switched off for the call:
        with it on, the parts arrive wrapped in one sub-assembly, out of reach
        of list_components and add_mate. The user's setting is restored after.
        """
        interconnect = sw.GetUserPreferenceToggle(SW_TOGGLE_3D_INTERCONNECT)
        if doc_type == SW_DOC_ASSEMBLY:
            sw.SetUserPreferenceToggle(SW_TOGGLE_3D_INTERCONNECT, False)
        before = {d.GetTitle() for d in self._open_documents()}
        try:
            doc, errors = self._load_file(sw, abs_path)
        finally:
            sw.SetUserPreferenceToggle(SW_TOGGLE_3D_INTERCONNECT, interconnect)
        model = binding.wrap(doc, self._mod.IModelDoc2)
        name = os.path.basename(abs_path)
        if model is None:
            # error 1 came with the parts it had made left open, hidden and unsaved
            raise SolidWorksError(
                f"SolidWorks could not import {abs_path} (error {errors}"
                f"{', no reason given' if errors == 1 else ''}).{self._close_new_documents(before)}"
            )
        if int(model.GetType()) != doc_type:
            raise SolidWorksError(
                (
                    f"{name} holds an assembly, not a part: open it with open_assembly."
                    if doc_type == SW_DOC_PART
                    else f"{name} holds a single part, not an assembly: open it with open_part."
                )
                + self._close_new_documents(before)
            )
        return model

    def _close_new_documents(self, before: set) -> str:
        """Close every document not open before, assemblies first (a part an
        open assembly holds stays); '' when all went, else what stayed."""
        for _ in range(3):
            # titles first: closing an assembly closes its parts, whose objects then answer nothing
            new = sorted(
                (int(d.GetType()) != SW_DOC_ASSEMBLY, d.GetTitle())
                for d in self._open_documents()
                if d.GetTitle() not in before
            )
            if not new:
                return ""
            for _, title in new:
                self._sw.CloseDoc(title)
        stayed = sorted(d.GetTitle() for d in self._open_documents() if d.GetTitle() not in before)
        return (
            f" It left open: {', '.join(stayed)}; close each with activate_document and close_part." if stayed else ""
        )

    @staticmethod
    def _load_file(sw, abs_path: str) -> tuple:
        """LoadFile4 with the format's own import settings: (document or None, errors)."""
        return sw.LoadFile4(abs_path, "r", sw.GetImportFileData(abs_path), 0)

    def run_guarded(self, fn, *args, **kwargs):
        """Run a tool; when it fails, delete what it added to the current part.

        Every MCP tool call goes through here, so a refused or failed call leaves
        the part as it was: no stray sketch, which would also count in the
        bounding box. A tool that switched documents is not rolled back.
        """
        self._reattach_if_gone()
        snapshot = self._history_snapshot()
        busy = self._command_in_progress(True)
        try:
            with self._quiet_ui():
                return fn(*args, **kwargs)
        except SolidWorksError as exc:
            left = self._roll_back(snapshot)
            if left:
                raise SolidWorksError(f"{exc} Could not remove what the call added: {', '.join(left)}.") from exc
            raise
        except Exception:
            self._roll_back(snapshot)
            raise
        finally:
            self._command_in_progress(busy)

    def _reattach_if_gone(self) -> None:
        """Attach to the running SolidWorks when the one this server held was
        restarted: the old link answers every call with an RPC error. The
        current document went with the old SolidWorks."""
        if self._sw is None:
            return
        try:
            self._sw.CommandInProgress
        except pythoncom.com_error as exc:
            if exc.hresult not in self._GONE_HRESULTS:
                raise
            self._sw = self._model = None
            self.connect()

    @contextlib.contextmanager
    def _quiet_ui(self):
        """Keep SolidWorks' window still while tools work on its documents.

        SOLIDWORKS 2026 SP4.0 crashed at random while the API sketched: an
        access violation in slduiu.dll, in its window message loop, also with
        CommandInProgress set. With the view, the feature tree and new sketch
        entities left undrawn it did not (6 crashes in 7 runs before, none in
        15 calls after). Everything is switched on and redrawn afterwards.
        """
        self._quiet_depth += 1
        try:
            yield
        finally:
            self._quiet_depth -= 1
            if not self._quiet_depth:
                self._wake_all()

    def _quiet(self, model) -> None:
        """Stop `model`'s view, feature tree and sketcher from redrawing, noting
        what was on so _wake_all switches just that back on."""
        view = binding.wrap(model.ActiveView, self._mod.IModelView)
        features = binding.wrap(model.FeatureManager, self._mod.IFeatureManager)
        sketches = binding.wrap(model.SketchManager, self._mod.ISketchManager)
        switched = []
        for target, prop in (
            (view, "EnableGraphicsUpdate"),
            (features, "EnableFeatureTree"),
            (features, "EnableFeatureTreeWindow"),
            (sketches, "DisplayWhenAdded"),
        ):
            if target is not None and getattr(target, prop):
                setattr(target, prop, False)
                switched.append((target, prop))
        if switched:
            self._to_wake.append((model, switched))

    def _wake_all(self) -> None:
        to_wake, self._to_wake = self._to_wake, []
        for model, switched in to_wake:
            try:
                for target, prop in switched:
                    setattr(target, prop, True)
                model.GraphicsRedraw2()
            except pythoncom.com_error:
                pass  # the document was closed during the call: nothing left to show

    def _command_in_progress(self, flag):
        """Set ISldWorks.CommandInProgress; return what it was when this changed
        it, else None, which leaves it alone when passed back. Set, SolidWorks
        stops redrawing between the calls of one command: COM calls ran 100
        times faster (144 edges read in 0.01 s, not 1.5 s; verified). It counts,
        every True needing its own False (verified), so it is only set when it
        is not already, and only that change is undone."""
        if self._sw is None or flag is None:
            return None
        before = bool(self._sw.CommandInProgress)
        if before == bool(flag):
            return None
        self._sw.CommandInProgress = bool(flag)
        return before

    @_reads_only  # before every tool call: reading the history needs no activation
    def _history_snapshot(self):
        """(title, history names) of the current part, or None without one."""
        if self._model is None or int(self._model.GetType()) != SW_DOC_PART:
            return None
        return self._model.GetTitle(), {f.Name for f in self._history()}

    def _roll_back(self, snapshot) -> list:
        if snapshot is None or self._model is None or self._model.GetTitle() != snapshot[0]:
            return []
        return self._remove_features_since(snapshot[1])

    def _remove_features_since(self, before: set) -> list:
        """Delete what the history gained since `before`, newest first; returns
        the names that could not be removed."""
        model = self._require_model()
        extension = binding.wrap(model.Extension, self._mod.IModelDocExtension)
        for feat in reversed([f for f in self._history() if f.Name not in before]):
            model.ClearSelection2(True)
            if feat.Select2(False, 0):
                extension.DeleteSelection2(SW_DELETE_ABSORBED)
        model.ForceRebuild3(False)
        return [f.Name for f in self._history() if f.Name not in before]
