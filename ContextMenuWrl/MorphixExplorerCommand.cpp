#include "MorphixExplorerCommand.h"
#include <shlwapi.h>
#include <shellapi.h>
#include <string>
#include <wrl/module.h>

using Microsoft::WRL::Module;

STDMETHODIMP MorphixExplorerCommand::GetTitle(IShellItemArray*, LPWSTR* ppszName)
{
    // Menu label shown in the Windows 11 top-level context menu.
    if (!ppszName)
    {
        return E_POINTER;
    }
    return SHStrDupW(L"Compress to 20MB", ppszName);
}

STDMETHODIMP MorphixExplorerCommand::GetIcon(IShellItemArray*, LPWSTR* ppszIcon)
{
    if (ppszIcon)
    {
        *ppszIcon = nullptr;
    }
    return E_NOTIMPL;
}

STDMETHODIMP MorphixExplorerCommand::GetToolTip(IShellItemArray*, LPWSTR* ppszInfotip)
{
    if (ppszInfotip)
    {
        *ppszInfotip = nullptr;
    }
    return E_NOTIMPL;
}

STDMETHODIMP MorphixExplorerCommand::GetCanonicalName(GUID* pguidCommandName)
{
    if (!pguidCommandName)
    {
        return E_POINTER;
    }
    *pguidCommandName = __uuidof(MorphixExplorerCommand);
    return S_OK;
}

STDMETHODIMP MorphixExplorerCommand::GetState(IShellItemArray*, BOOL, EXPCMDSTATE* pCmdState)
{
    if (!pCmdState)
    {
        return E_POINTER;
    }
    *pCmdState = ECS_ENABLED;
    return S_OK;
}

STDMETHODIMP MorphixExplorerCommand::Invoke(IShellItemArray* psiItemArray, IBindCtx*)
{
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

    // Hardcoded EXE location for the Python-built binary.
    std::wstring exePath = L"C:\\Users\\flori\\source\\repos\\morphix-prototype\\dist\\Morphix.exe";

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
    if (!pFlags)
    {
        return E_POINTER;
    }
    *pFlags = ECF_DEFAULT;
    return S_OK;
}

STDMETHODIMP MorphixExplorerCommand::EnumSubCommands(IEnumExplorerCommand** ppEnum)
{
    if (ppEnum)
    {
        *ppEnum = nullptr;
    }
    return E_NOTIMPL;
}

CoCreatableClass(MorphixExplorerCommand);
