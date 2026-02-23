#include <wrl.h>
#include <wrl/module.h>
#include <windows.h>

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID)
{
    if (ul_reason_for_call == DLL_PROCESS_ATTACH)
    {
        Microsoft::WRL::Module<Microsoft::WRL::InProc>::GetModule().Create();
    }
    else if (ul_reason_for_call == DLL_PROCESS_DETACH)
    {
        Microsoft::WRL::Module<Microsoft::WRL::InProc>::GetModule().Terminate();
    }
    return TRUE;
}

STDAPI DllCanUnloadNow(void)
{
    // COM server lifetime: allow unload when no active objects remain.
    return Microsoft::WRL::Module<Microsoft::WRL::InProc>::GetModule().GetObjectCount() == 0 ? S_OK : S_FALSE;
}

STDAPI DllGetClassObject(REFCLSID rclsid, REFIID riid, LPVOID* ppv)
{
    // Factory used by COM to create the command handler.
    return Microsoft::WRL::Module<Microsoft::WRL::InProc>::GetModule().GetClassObject(rclsid, riid, ppv);
}
