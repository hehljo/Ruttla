#include "DemoChar.h"
UCLASS()
class ADemoChar : public ACharacter { GENERATED_BODY() };
ADemoChar::ADemoChar()
{
    VisibleBody = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Body"));
    VisibleBody->SetupAttachment(GetMesh());
    VisibleHead = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Head"));
    VisibleHead->SetupAttachment(GetMesh());
}
void ADemoChar::BeginPlay()
{
    Super::BeginPlay();
    VisibleBody->SetLeaderPoseComponent(GetMesh(), true, false);
    VisibleHead->SetLeaderPoseComponent(GetMesh(), true, false);
}
