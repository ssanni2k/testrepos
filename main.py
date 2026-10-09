import os
import sys

import dropbox
from dropbox.files import WriteMode, FolderMetadata, FileMetadata
from dropbox.exceptions import ApiError, AuthError
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DROPBOX_TOKEN")
if not TOKEN:
    print("Ошибка: переменная DROPBOX_TOKEN не найдена в .env")
    sys.exit(1)

dbx = dropbox.Dropbox(TOKEN)


def bytes_to_readable(n):
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} ПБ"


def safe_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except AuthError as e:
        print(f"Ошибка авторизации: {e}")
    except ApiError as e:
        msg = getattr(e.error, "_tag", str(e))
        print(f"Ошибка API: {msg}")
    except Exception as e:
        print(f"Неожиданная ошибка: {e}")
    return None


# ---------- Пользователь и место ----------

def show_user_info():
    acc = safe_call(dbx.users_get_current_account)
    if acc is None:
        return
    print("\n=== Информация о пользователе ===")
    print(f"Имя:         {acc.name.display_name}")
    print(f"Email:       {acc.email}")
    print(f"ID аккаунта: {acc.account_id}")
    print(f"Тип:         {acc.account_type._tag}")
    print(f"Страна:      {acc.country}")


def show_space_usage():
    usage = safe_call(dbx.users_get_space_usage)
    if usage is None:
        return
    if usage.allocation.is_individual():
        allocated = usage.allocation.get_individual().allocated
    else:
        allocated = usage.allocation.get_team().allocated
    used = usage.used
    free = allocated - used
    percent = used / allocated * 100 if allocated else 0
    print("\n=== Место в хранилище ===")
    print(f"Всего:    {bytes_to_readable(allocated)}")
    print(f"Занято:   {bytes_to_readable(used)} ({percent:.1f}%)")
    print(f"Свободно: {bytes_to_readable(free)}")


# ---------- Папки ----------

def list_folder(path=""):
    result = safe_call(dbx.files_list_folder, path)
    if result is None:
        return
    entries = list(result.entries)
    while result.has_more:
        result = safe_call(dbx.files_list_folder_continue, result.cursor)
        if result is None:
            break
        entries.extend(result.entries)
    if not entries:
        print("Папка пуста.")
        return
    for e in entries:
        if isinstance(e, FolderMetadata):
            print(f"[ПАПКА] {e.name}")
        elif isinstance(e, FileMetadata):
            print(f"[ФАЙЛ]  {e.name}  ({bytes_to_readable(e.size)})")


def create_folder(path):
    res = safe_call(dbx.files_create_folder_v2, path)
    if res:
        print(f"Папка создана: {res.metadata.path_display}")


def move_entry(src, dst):
    res = safe_call(dbx.files_move_v2, src, dst)
    if res:
        print(f"Перемещено: {src} -> {dst}")


def delete_entry(path):
    res = safe_call(dbx.files_delete_v2, path)
    if res:
        print(f"Удалено: {res.metadata.path_display}")


# ---------- Файлы ----------

def upload_file(local_path, remote_path, overwrite=False):
    if not os.path.isfile(local_path):
        print(f"Локальный файл не найден: {local_path}")
        return
    mode = WriteMode.overwrite if overwrite else WriteMode.add
    with open(local_path, "rb") as f:
        res = safe_call(dbx.files_upload, f.read(), remote_path, mode=mode)
    if res:
        print(f"Загружено: {res.path_display}  ({bytes_to_readable(res.size)})")


def download_file(remote_path, local_path):
    res = safe_call(dbx.files_download, remote_path)
    if res is None:
        return
    metadata, response = res
    with open(local_path, "wb") as f:
        f.write(response.content)
    print(f"Скачано: {remote_path} -> {local_path}")


def copy_entry(src, dst):
    res = safe_call(dbx.files_copy_v2, src, dst)
    if res:
        print(f"Скопировано: {src} -> {dst}")


# ---------- Метаданные ----------

def show_metadata(path):
    m = safe_call(dbx.files_get_metadata, path)
    if m is None:
        return
    print("\n=== Метаданные ===")
    print(f"Имя:  {m.name}")
    print(f"Путь: {m.path_display}")
    if isinstance(m, FileMetadata):
        print("Тип:  файл")
        print(f"Размер: {bytes_to_readable(m.size)}")
        print(f"Изменён: {m.server_modified}")
        print(f"ID: {m.id}")
        print(f"Ревизия: {m.rev}")
    elif isinstance(m, FolderMetadata):
        print("Тип:  папка")
        print(f"ID: {m.id}")


# ---------- Шаринг ----------

def create_share_link(path):
    settings = dropbox.sharing.SharedLinkSettings(
        requested_visibility=dropbox.sharing.RequestedVisibility.public
    )
    res = safe_call(dbx.sharing_create_shared_link_with_settings, path, settings)
    if res:
        print(f"Ссылка: {res.url}")
    else:
        existing = safe_call(dbx.sharing_list_shared_links, path=path)
        if existing and existing.links:
            print(f"Ссылка уже существует: {existing.links[0].url}")


def list_shared_links():
    res = safe_call(dbx.sharing_list_shared_links)
    if res is None:
        return
    if not res.links:
        print("Расшаренных ресурсов нет.")
        return
    print("\n=== Расшаренные ресурсы ===")
    for link in res.links:
        kind = "папка" if isinstance(link, dropbox.sharing.FolderLinkMetadata) else "файл"
        print(f"[{kind}] {link.name}")
        print(f"  Путь: {getattr(link, 'path_lower', '—')}")
        print(f"  URL:  {link.url}")
        if isinstance(link, dropbox.sharing.FileLinkMetadata):
            print(f"  Изменён: {link.client_modified}")
        print()

# ---------- Поиск ----------

def search(query, filename_only=False):
    options = dropbox.files.SearchOptions(
        path="",
        max_results=20,
        filename_only=filename_only,
    )
    res = safe_call(dbx.files_search_v2, query, options)
    if res is None:
        return
    if not res.matches:
        print("Ничего не найдено.")
        return
    print(f"\nНайдено совпадений: {len(res.matches)}")
    for match in res.matches:
        meta = match.metadata.get_metadata()
        kind = "папка" if isinstance(meta, FolderMetadata) else "файл"
        print(f"[{kind}] {meta.path_display}")


# ---------- Меню ----------

def prompt(label, default=None):
    value = input(label).strip()
    if not value and default is not None:
        return default
    return value


def menu():
    while True:
        print("\n========== Dropbox Lab ==========")
        print("1.  Информация о пользователе")
        print("2.  Место в хранилище")
        print("3.  Содержимое папки")
        print("4.  Создать папку")
        print("5.  Переместить папку/файл")
        print("6.  Удалить папку/файл")
        print("7.  Загрузить файл")
        print("8.  Скачать файл")
        print("9.  Заменить файл (overwrite)")
        print("10. Скопировать файл")
        print("11. Метаданные файла/папки")
        print("12. Создать ссылку для шаринга")
        print("13. Список расшаренных ресурсов")
        print("14. Поиск по имени")
        print("15. Поиск по содержимому")
        print("0.  Выход")
        choice = input("Выберите пункт: ").strip()

        try:
            if choice == "1":
                show_user_info()
            elif choice == "2":
                show_space_usage()
            elif choice == "3":
                list_folder(prompt("Путь к папке (Enter — корень): ", ""))
            elif choice == "4":
                create_folder(prompt("Путь новой папки (например /Новая): "))
            elif choice == "5":
                src = prompt("Откуда: ")
                dst = prompt("Куда: ")
                move_entry(src, dst)
            elif choice == "6":
                delete_entry(prompt("Путь: "))
            elif choice == "7":
                local = prompt("Локальный файл: ")
                remote = prompt("Путь в Dropbox (например /file.txt): ")
                upload_file(local, remote)
            elif choice == "8":
                remote = prompt("Путь в Dropbox: ")
                local = prompt("Куда сохранить локально: ")
                download_file(remote, local)
            elif choice == "9":
                local = prompt("Локальный файл: ")
                remote = prompt("Путь в Dropbox: ")
                upload_file(local, remote, overwrite=True)
            elif choice == "10":
                src = prompt("Откуда: ")
                dst = prompt("Куда: ")
                copy_entry(src, dst)
            elif choice == "11":
                show_metadata(prompt("Путь: "))
            elif choice == "12":
                create_share_link(prompt("Путь к файлу/папке: "))
            elif choice == "13":
                list_shared_links()
            elif choice == "14":
                search(prompt("Запрос (по имени): "), filename_only=True)
            elif choice == "15":
                search(prompt("Запрос (по содержимому): "), filename_only=False)
            elif choice == "0":
                print("Пока!")
                break
            else:
                print("Неизвестная команда.")
        except KeyboardInterrupt:
            print("\nПрервано.")


if __name__ == "__main__":
    menu()
