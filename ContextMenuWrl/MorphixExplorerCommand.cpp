#include "MorphixExplorerCommand.h"
#include <shlwapi.h>
#include <shellapi.h>
#include <string>
#include <wrl/module.h>
#include <commctrl.h>

using Microsoft::WRL::Module;

// Namespace-scope anchors for GetModuleHandleExW address-of trick.
static int s_anchor_compr = 0;
static int s_anchor_open  = 0;

STDMETHODIMP MorphixExplorerCommand::GetTitle(IShellItemArray*, LPWSTR* ppszName)
{
    // Menu label shown in the Windows 11 top-level context menu.
    if (!ppszName)
    {
        return E_POINTER;
    }
    return SHStrDupW(L"Compress with Morphix", ppszName);
}

STDMETHODIMP MorphixExplorerCommand::GetIcon(IShellItemArray*, LPWSTR* ppszIcon)
{
    // No icon for now. Returning E_NOTIMPL tells Explorer to skip it.
    if (ppszIcon)
    {
        *ppszIcon = nullptr;
    }
    return E_NOTIMPL;
}

STDMETHODIMP MorphixExplorerCommand::GetToolTip(IShellItemArray*, LPWSTR* ppszInfotip)
{
    // No tooltip for now.
    if (ppszInfotip)
    {
        *ppszInfotip = nullptr;
    }
    return E_NOTIMPL;
}

STDMETHODIMP MorphixExplorerCommand::GetCanonicalName(GUID* pguidCommandName)
{
    // Required COM identity for this command.
    if (!pguidCommandName)
    {
        return E_POINTER;
    }
    *pguidCommandName = __uuidof(MorphixExplorerCommand);
    return S_OK;
}

STDMETHODIMP MorphixExplorerCommand::GetState(IShellItemArray*, BOOL, EXPCMDSTATE* pCmdState)
{
    // Always enabled; change this to disable based on selection.
    if (!pCmdState)
    {
        return E_POINTER;
    }
    *pCmdState = ECS_ENABLED;
    return S_OK;
}

STDMETHODIMP MorphixExplorerCommand::Invoke(IShellItemArray* psiItemArray, IBindCtx*)
{
    // Actual action when the menu item is clicked.
    if (!psiItemArray)
    {
        return E_INVALIDARG;
    }

    Microsoft::WRL::ComPtr<IShellItem> item;
    HRESULT hr = psiItemArray->GetItemAt(0, &item);
    if (FAILED(hr))
    {
        return hr;
    }

    PWSTR path = nullptr;
    hr = item->GetDisplayName(SIGDN_FILESYSPATH, &path);
    if (FAILED(hr))
    {
        return hr;
    }

    std::wstring inputPath = path;
    CoTaskMemFree(path);
    if (inputPath.empty())
    {
        return E_FAIL;
    }

    // Resolve EXE path relative to this DLL's location.
    wchar_t dllPath[MAX_PATH] = {};
    HMODULE hModule = nullptr;
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(&s_anchor_compr),
        &hModule);
    GetModuleFileNameW(hModule, dllPath, MAX_PATH);
    std::wstring dllDir = dllPath;
    size_t lastSlash = dllDir.find_last_of(L'\\');
    if (lastSlash != std::wstring::npos)
    {
        dllDir = dllDir.substr(0, lastSlash);
    }
    std::wstring exePath = dllDir + L"\\Morphix.exe";

    // Build output path: same folder, with "-morphix-compressed" before extension.
    std::wstring outputPath = inputPath;
    size_t dotPos = outputPath.find_last_of(L'.');
    if (dotPos == std::wstring::npos)
    {
        outputPath.append(L"-morphix-compressed");
    }
    else
    {
        outputPath.insert(dotPos, L"-morphix-compressed");
    }

    // Show a confirmation dialog pre-populated with the default target size of 20 MB.
    int nButton = 0;
    TASKDIALOGCONFIG tdc = { sizeof(tdc) };
    tdc.hwndParent = nullptr;
    tdc.pszWindowTitle = L"Compress with Morphix";
    tdc.pszMainInstruction = L"Compress video";
    tdc.pszContent = L"Compress to 20 MB?";
    tdc.dwCommonButtons = TDCBF_OK_BUTTON | TDCBF_CANCEL_BUTTON;
    TaskDialogIndirect(&tdc, &nButton, nullptr, nullptr);
    if (nButton != IDOK)
    {
        return S_OK;
    }

    // Forward the selected file and target size to Morphix.
    std::wstring args = L"\"" + inputPath + L"\" --max-mb 20 --output \"" + outputPath + L"\"";

    SHELLEXECUTEINFOW sei = { sizeof(sei) };
    sei.fMask = SEE_MASK_NOASYNC;
    sei.lpFile = exePath.c_str();
    sei.lpParameters = args.c_str();
    sei.nShow = SW_SHOWNORMAL;
    // Launch Morphix without blocking Explorer.
    ShellExecuteExW(&sei);

    return S_OK;
}

STDMETHODIMP MorphixExplorerCommand::GetFlags(EXPCMDFLAGS* pFlags)
{
    // Default command behavior.
    if (!pFlags)
    {
        return E_POINTER;
    }
    *pFlags = ECF_DEFAULT;
    return S_OK;
}

STDMETHODIMP MorphixExplorerCommand::EnumSubCommands(IEnumExplorerCommand** ppEnum)
{
    // No subcommands for now.
    if (ppEnum)
    {
        *ppEnum = nullptr;
    }
    return E_NOTIMPL;
}

CoCreatableClass(MorphixExplorerCommand);

// ---------------------------------------------------------------------------
// MorphixOpenCommand — "Open in Morphix" context menu entry (Requirement 17)
// ---------------------------------------------------------------------------

STDMETHODIMP MorphixOpenCommand::GetTitle(IShellItemArray*, LPWSTR* ppszName)
{
    if (!ppszName) return E_POINTER;
    return SHStrDupW(L"Open in Morphix", ppszName);
}

STDMETHODIMP MorphixOpenCommand::GetIcon(IShellItemArray*, LPWSTR* ppszIcon)
{
    if (ppszIcon) *ppszIcon = nullptr;
    return E_NOTIMPL;
}

STDMETHODIMP MorphixOpenCommand::GetToolTip(IShellItemArray*, LPWSTR* ppszInfotip)
{
    if (ppszInfotip) *ppszInfotip = nullptr;
    return E_NOTIMPL;
}

STDMETHODIMP MorphixOpenCommand::GetCanonicalName(GUID* pguidCommandName)
{
    if (!pguidCommandName) return E_POINTER;
    *pguidCommandName = __uuidof(MorphixOpenCommand);
    return S_OK;
}

STDMETHODIMP MorphixOpenCommand::GetState(IShellItemArray*, BOOL, EXPCMDSTATE* pCmdState)
{
    if (!pCmdState) return E_POINTER;
    *pCmdState = ECS_ENABLED;
    return S_OK;
}

STDMETHODIMP MorphixOpenCommand::Invoke(IShellItemArray* psiItemArray, IBindCtx*)
{
    if (!psiItemArray) return E_INVALIDARG;

    Microsoft::WRL::ComPtr<IShellItem> item;
    HRESULT hr = psiItemArray->GetItemAt(0, &item);
    if (FAILED(hr)) return hr;

    PWSTR path = nullptr;
    hr = item->GetDisplayName(SIGDN_FILESYSPATH, &path);
    if (FAILED(hr)) return hr;

    std::wstring inputPath = path;
    CoTaskMemFree(path);
    if (inputPath.empty()) return E_FAIL;

    // Resolve Morphix_UI.exe relative to this DLL's location.
    wchar_t dllPath[MAX_PATH] = {};
    HMODULE hModule = nullptr;
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(&s_anchor_open),
        &hModule);
    GetModuleFileNameW(hModule, dllPath, MAX_PATH);
    std::wstring dllDir = dllPath;
    size_t lastSlash = dllDir.find_last_of(L'\\');
    if (lastSlash != std::wstring::npos) dllDir = dllDir.substr(0, lastSlash);
    std::wstring exePath = dllDir + L"\\Morphix_UI.exe";

    // Pass the selected file as a positional argument to the UI.
    std::wstring args = L"\"" + inputPath + L"\"";

    SHELLEXECUTEINFOW sei = { sizeof(sei) };
    // Non-blocking launch: do not use SEE_MASK_NOASYNC or SEE_MASK_NOCLOSEPROCESS.
    sei.lpFile = exePath.c_str();
    sei.lpParameters = args.c_str();
    sei.nShow = SW_SHOWNORMAL;
    ShellExecuteExW(&sei);

    return S_OK;
}

STDMETHODIMP MorphixOpenCommand::GetFlags(EXPCMDFLAGS* pFlags)
{
    if (!pFlags) return E_POINTER;
    *pFlags = ECF_DEFAULT;
    return S_OK;
}

STDMETHODIMP MorphixOpenCommand::EnumSubCommands(IEnumExplorerCommand** ppEnum)
{
    if (ppEnum) *ppEnum = nullptr;
    return E_NOTIMPL;
}

CoCreatableClass(MorphixOpenCommand);
