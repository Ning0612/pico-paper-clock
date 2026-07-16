import gc
import os
import random
import time

from image_codec import inspect_file, validate_file


IMAGE_ROOT = "/image"
SAFE_FREE_BYTES = 32 * 1024
UPLOAD_BUFFER_BYTES = 512

IMAGE_SPECS = {
    "custom": (128, 128, 2048),
    "login": (296, 128, 4736),
    "events": (128, 128, 2048),
}


def _ticks_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.monotonic() * 1000)


def _ticks_diff(new, old):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(new, old)
    return new - old


class ImageStoreError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _is_file(entry):
    if len(entry) > 1 and entry[1]:
        return entry[1] == 0x8000
    return True


def _iter_dir(path):
    try:
        iterator = os.ilistdir(path)
        for entry in iterator:
            if _is_file(entry):
                yield entry[0]
        return
    except (AttributeError, OSError):
        pass

    try:
        for name in os.listdir(path):
            try:
                mode = os.stat(path + "/" + name)[0]
                if mode & 0x4000:
                    continue
            except OSError:
                continue
            yield name
    except OSError:
        return


def _ensure_dir(path):
    if _exists(path):
        return
    parent = path.rsplit("/", 1)[0]
    if parent and parent != path:
        _ensure_dir(parent)
    try:
        os.mkdir(path)
    except OSError:
        if not _exists(path):
            raise


def validate_filename(filename):
    if not isinstance(filename, str):
        raise ImageStoreError("invalid_name", "Image filename must be text.")
    if not filename.endswith(".bin"):
        raise ImageStoreError("invalid_name", "Image filename must end with .bin.")
    base = filename[:-4]
    if not base or len(base) > 48:
        raise ImageStoreError("invalid_name", "Image base name must contain 1-48 characters.")
    for char in base:
        code = ord(char)
        ascii_alnum = (ord("A") <= code <= ord("Z") or
                       ord("a") <= code <= ord("z") or
                       ord("0") <= code <= ord("9"))
        if not ascii_alnum and char not in "_-":
            raise ImageStoreError("invalid_name", "Use ASCII letters, digits, underscore, or hyphen.")
    return filename


def validate_event(event):
    if event == "birthday":
        return event
    if not isinstance(event, str) or len(event) != 4 or any(char < "0" or char > "9" for char in event):
        raise ImageStoreError("invalid_event", "Event must be birthday or MMDD.")
    month = int(event[:2])
    day = int(event[2:])
    month_days = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if month < 1 or month > 12 or day < 1 or day > month_days[month - 1]:
        raise ImageStoreError("invalid_event", "Event date is not valid.")
    return event


def image_directory(collection, event=None):
    if collection not in IMAGE_SPECS:
        raise ImageStoreError("invalid_collection", "Unsupported image collection.")
    if collection == "events":
        return IMAGE_ROOT + "/events/" + validate_event(event)
    return IMAGE_ROOT + "/" + collection


def image_path(collection, filename, event=None):
    return image_directory(collection, event) + "/" + validate_filename(filename)


def image_spec(collection):
    try:
        return IMAGE_SPECS[collection]
    except KeyError:
        raise ImageStoreError("invalid_collection", "Unsupported image collection.")


def filesystem_free(path=IMAGE_ROOT):
    try:
        stats = os.statvfs(path)
        return int(stats[1]) * int(stats[4])
    except (AttributeError, OSError, IndexError):
        return -1


class ImageStore:
    __slots__ = ("catalog_generation", "pending_preview")

    def __init__(self):
        self.catalog_generation = 0
        self.pending_preview = None

    def invalidate(self):
        self.catalog_generation += 1

    def iter_images(self, collection, event=None):
        directory = image_directory(collection, event)
        expected = image_spec(collection)[2]
        for filename in _iter_dir(directory):
            if not filename.endswith(".bin") or filename.endswith(".part"):
                continue
            try:
                validate_filename(filename)
                path = directory + "/" + filename
                size = os.stat(path)[6]
                inspect_file(path, expected)
            except (OSError, ImageStoreError, IndexError, ValueError):
                continue
            yield filename, int(size)

    def upload(self, stream, collection, filename, content_length, event=None,
               overwrite=False, preview=False):
        width, height, expected_length = image_spec(collection)
        max_length = expected_length * 2 + 64
        if content_length <= 0 or content_length > max_length:
            raise ImageStoreError(
                "invalid_size",
                "Expected a raw or PPC1-compressed {}x{} image.".format(width, height)
            )

        target = image_path(collection, filename, event)
        if _exists(target) and not overwrite:
            raise ImageStoreError("exists", "Image already exists.")

        free_bytes = filesystem_free(IMAGE_ROOT)
        if free_bytes >= 0 and free_bytes - content_length < SAFE_FREE_BYTES:
            raise ImageStoreError("insufficient_storage", "Not enough device storage.")

        directory = image_directory(collection, event)
        _ensure_dir(directory)
        part_path = target + ".part"
        backup_path = target + ".bak"
        marker_path = target + ".hlsb"
        marker_part_path = marker_path + ".part"
        marker_backup_path = marker_path + ".bak"
        target_moved = False
        marker_moved = False
        target_installed = False
        marker_installed = False
        try:
            for stale_path in (part_path, marker_part_path):
                try:
                    os.remove(stale_path)
                except OSError:
                    pass

            remaining = content_length
            buffer = bytearray(min(UPLOAD_BUFFER_BYTES, content_length))
            with open(part_path, "wb") as output:
                while remaining:
                    requested = min(len(buffer), remaining)
                    try:
                        count = stream.readinto(buffer, requested)
                    except TypeError:
                        count = stream.readinto(memoryview(buffer)[:requested])
                    if not count:
                        raise ImageStoreError("incomplete_upload", "Upload ended before all bytes arrived.")
                    output.write(memoryview(buffer)[:count])
                    remaining -= count

            actual_length = os.stat(part_path)[6]
            if actual_length != content_length:
                raise ImageStoreError("invalid_size", "Stored image length does not match request.")
            try:
                compressed, _ = validate_file(part_path, expected_length)
            except (OSError, ValueError):
                raise ImageStoreError(
                    "invalid_size",
                    "Image payload is not a valid raw or PPC1-compressed {}x{} image.".format(
                        width, height
                    )
                )
            marker_needed = not compressed
            if marker_needed:
                with open(marker_part_path, "wb") as marker_file:
                    marker_file.write(b"1")
            if hasattr(os, "sync"):
                os.sync()

            replaced = _exists(target)
            if replaced:
                try:
                    os.remove(backup_path)
                except OSError:
                    pass
                os.rename(target, backup_path)
                target_moved = True
            if _exists(marker_path):
                try:
                    os.remove(marker_backup_path)
                except OSError:
                    pass
                os.rename(marker_path, marker_backup_path)
                marker_moved = True
            os.rename(part_path, target)
            target_installed = True
            if marker_needed:
                os.rename(marker_part_path, marker_path)
                marker_installed = True
            if hasattr(os, "sync"):
                os.sync()
            if target_moved:
                try:
                    os.remove(backup_path)
                except OSError:
                    pass
            if marker_moved:
                try:
                    os.remove(marker_backup_path)
                except OSError:
                    pass
            self.invalidate()
            if preview:
                self.pending_preview = (target, width, height)
            return {
                "path": target,
                "bytes": content_length,
                "uncompressed_bytes": expected_length,
                "compressed": compressed,
                "replaced": replaced,
                "preview_queued": bool(preview),
                "catalog_generation": self.catalog_generation,
            }
        except ImageStoreError:
            self._rollback_upload(
                target, part_path, backup_path, target_moved, target_installed,
                marker_path, marker_part_path, marker_backup_path,
                marker_moved, marker_installed,
            )
            raise
        except Exception as exc:
            print("Image upload failed: {}".format(exc))
            self._rollback_upload(
                target, part_path, backup_path, target_moved, target_installed,
                marker_path, marker_part_path, marker_backup_path,
                marker_moved, marker_installed,
            )
            raise ImageStoreError("write_failed", "Unable to store image.")
        finally:
            gc.collect()

    def _rollback_upload(self, target, part_path, backup_path, target_moved,
                         target_installed, marker_path, marker_part_path,
                         marker_backup_path, marker_moved, marker_installed):
        for path in (part_path, marker_part_path):
            try:
                os.remove(path)
            except OSError:
                pass
        if marker_installed:
            try:
                os.remove(marker_path)
            except OSError:
                pass
        if target_installed:
            try:
                os.remove(target)
            except OSError:
                pass
        if target_moved and _exists(backup_path):
            try:
                os.rename(backup_path, target)
            except OSError:
                pass
        if marker_moved and _exists(marker_backup_path):
            try:
                os.rename(marker_backup_path, marker_path)
            except OSError:
                pass

    def delete(self, collection, filename, event=None):
        target = image_path(collection, filename, event)
        if not _exists(target):
            raise ImageStoreError("not_found", "Image does not exist.")
        try:
            os.remove(target)
            try:
                os.remove(target + ".hlsb")
            except OSError:
                pass
            self.invalidate()
            return target
        except OSError as exc:
            print("Image delete failed: {}".format(exc))
            raise ImageStoreError("delete_failed", "Unable to delete image.")

    def queue_preview(self, collection, filename, event=None):
        target = image_path(collection, filename, event)
        if not _exists(target):
            raise ImageStoreError("not_found", "Image does not exist.")
        width, height, expected = image_spec(collection)
        try:
            inspect_file(target, expected)
        except (OSError, ValueError):
            raise ImageStoreError("not_found", "Image does not exist.")
        self.pending_preview = (target, width, height)
        return target

    def consume_preview(self):
        preview = self.pending_preview
        self.pending_preview = None
        return preview

    def recover_partial_uploads(self):
        recovered = 0
        directories = [IMAGE_ROOT + "/custom", IMAGE_ROOT + "/login"]
        events_root = IMAGE_ROOT + "/events"
        try:
            for entry in os.ilistdir(events_root):
                if len(entry) > 1 and entry[1] == 0x4000:
                    directories.append(events_root + "/" + entry[0])
        except (AttributeError, OSError):
            try:
                for name in os.listdir(events_root):
                    directories.append(events_root + "/" + name)
            except OSError:
                pass

        for directory in directories:
            recovery = {}
            for name in _iter_dir(directory):
                if name.endswith(".bin.part"):
                    target_name = name[:-5]
                    recovery.setdefault(target_name, {})["part"] = directory + "/" + name
                elif name.endswith(".bin.bak"):
                    target_name = name[:-4]
                    recovery.setdefault(target_name, {})["backup"] = directory + "/" + name
                elif name.endswith(".bin.hlsb.part"):
                    target_name = name[:-10]
                    recovery.setdefault(target_name, {})["marker_part"] = directory + "/" + name
                elif name.endswith(".bin.hlsb.bak"):
                    target_name = name[:-9]
                    recovery.setdefault(target_name, {})["marker_backup"] = directory + "/" + name

            for target_name, files in recovery.items():
                target = directory + "/" + target_name
                part_path = files.get("part")
                backup_path = files.get("backup")
                marker_path = target + ".hlsb"
                marker_part_path = files.get("marker_part")
                marker_backup_path = files.get("marker_backup")
                collection = "login" if directory.endswith("/login") else (
                    "custom" if directory.endswith("/custom") else "events"
                )
                expected = IMAGE_SPECS[collection][2]
                try:
                    if _exists(target):
                        if marker_part_path and not part_path:
                            try:
                                target_compressed, _ = inspect_file(target, expected)
                            except (OSError, ValueError):
                                target_compressed = True
                            if target_compressed:
                                os.remove(marker_part_path)
                            else:
                                try:
                                    os.remove(marker_path)
                                except OSError:
                                    pass
                                os.rename(marker_part_path, marker_path)
                        if part_path:
                            os.remove(part_path)
                            if marker_part_path:
                                os.remove(marker_part_path)
                        if backup_path:
                            os.remove(backup_path)
                        if marker_backup_path:
                            os.remove(marker_backup_path)
                        continue
                    valid_part = False
                    part_compressed = False
                    if part_path:
                        try:
                            part_compressed, _ = validate_file(part_path, expected)
                            valid_part = True
                        except (OSError, ValueError):
                            valid_part = False
                    if valid_part and (part_compressed or marker_part_path):
                        os.rename(part_path, target)
                        if part_compressed and marker_part_path:
                            os.remove(marker_part_path)
                        elif marker_part_path:
                            os.rename(marker_part_path, marker_path)
                        recovered += 1
                        if backup_path:
                            os.remove(backup_path)
                        if marker_backup_path:
                            os.remove(marker_backup_path)
                    elif backup_path:
                        try:
                            validate_file(backup_path, expected)
                        except (OSError, ValueError):
                            backup_path = None
                    if not valid_part and backup_path:
                        os.rename(backup_path, target)
                        if marker_backup_path:
                            os.rename(marker_backup_path, marker_path)
                        recovered += 1
                        if part_path:
                            os.remove(part_path)
                        if marker_part_path:
                            os.remove(marker_part_path)
                    else:
                        if part_path:
                            os.remove(part_path)
                        if marker_part_path:
                            os.remove(marker_part_path)
                except OSError:
                    pass
        if recovered:
            self.invalidate()
        return recovered


class ImageCatalog:
    __slots__ = (
        "store", "seen_generation", "current_path", "current_directory",
        "last_change_ms", "force_advance",
    )

    def __init__(self, store):
        self.store = store
        self.seen_generation = -1
        self.current_path = None
        self.current_directory = None
        self.last_change_ms = _ticks_ms()
        self.force_advance = False
        random.seed(_ticks_ms())

    def invalidate(self):
        self.seen_generation = -1

    def advance(self):
        self.force_advance = True

    def _choose(self, directory, previous=None):
        chosen = None
        count = 0
        fallback = None
        expected = IMAGE_SPECS["login"][2] if directory.endswith("/login") else IMAGE_SPECS["custom"][2]
        for filename in _iter_dir(directory):
            if not filename.endswith(".bin") or filename.endswith(".part"):
                continue
            full_path = directory + "/" + filename
            try:
                inspect_file(full_path, expected)
            except (OSError, ValueError):
                continue
            fallback = full_path
            if full_path == previous:
                continue
            count += 1
            if random.randint(1, count) == 1:
                chosen = full_path
        return chosen or fallback

    def select(self, date_mmdd, birthday_mmdd, interval_min):
        if date_mmdd == birthday_mmdd:
            birthday_dir = IMAGE_ROOT + "/events/birthday"
            if self._choose(birthday_dir):
                directory = birthday_dir
            else:
                directory = None
        else:
            directory = None

        event_dir = IMAGE_ROOT + "/events/" + date_mmdd
        if directory is None and self._choose(event_dir):
            directory = event_dir
        if directory is None:
            directory = IMAGE_ROOT + "/custom"

        now_ms = _ticks_ms()
        interval_ms = max(1, int(interval_min)) * 60 * 1000
        dirty = self.seen_generation != self.store.catalog_generation
        due = _ticks_diff(now_ms, self.last_change_ms) >= interval_ms
        if directory != self.current_directory or self.current_path is None or due or dirty or self.force_advance:
            previous = self.current_path if directory == self.current_directory else None
            self.current_path = self._choose(directory, previous)
            self.current_directory = directory
            self.last_change_ms = now_ms
            self.seen_generation = self.store.catalog_generation
            self.force_advance = False
        return self.current_path

    def select_loading(self):
        return self._choose(IMAGE_ROOT + "/login")


image_store = ImageStore()
image_catalog = ImageCatalog(image_store)
