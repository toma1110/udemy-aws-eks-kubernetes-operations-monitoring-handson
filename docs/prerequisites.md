# 事前準備

このコースのAWS演習は、AWS Management Consoleから開くAWS CloudShellのBashを使います。ローカルPCのPowerShellは必要ありません。

## 1. 東京リージョンでCloudShellを開く

AWS Management Consoleで東京リージョン `ap-northeast-1` を選び、CloudShellを開きます。promptが表示されたら、次のcommandでBashとRegionを確認します。

```bash
bash --version
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="ap-northeast-1"
aws configure list
```

`aws configure list`のRegionが`ap-northeast-1`でない場合は、後続の演習へ進みません。

## 2. ツールと保存領域を確認する

AWS公式ドキュメントでは、CloudShellにAWS CLI、kubectl、jqがあらかじめ用意されています。具体的なversionは固定されていないため、演習のたびに現在のversionを確認します。

```bash
aws --version
kubectl version --client --output=json
jq --version
python3 --version
printf 'HOME=%s\n' "$HOME"
df -h "$HOME"
```

期待結果:

- AWS CLI、kubectl、jq、Python 3のversionが表示される。
- `$HOME`の使用量と空き容量が表示される。
- 通常のCloudShellでは、`$HOME`にRegionごとに1 GBの永続領域がある。

CloudShell VPC環境には永続領域がありません。この演習では通常のCloudShellを使います。version確認が失敗した場合は、installを始めず、CloudShellを開き直して同じcommandを再確認してください。それでも見つからない場合は、環境が通常のCloudShellかを管理者へ確認します。

## 3. EKS環境を確認する

Section 4以降のEKS演習では、コース共通の短時間EKS環境を使います。環境がない場合だけ、[共通EKS環境のREADME](../labs/common-eks/README.md)に従って作成します。

共通環境を作成する前に、次を確認します。

- AWS Management Consoleで表示される利用予定のaccountとRegionが正しい。
- EKS、CloudFormation、EC2、EBS、IAM、CloudWatchを扱うために必要な権限がある。
- EKS control plane、managed node、EBS、public IPv4、CloudWatchの料金をAWS公式ページで確認した。
- 最大6時間以内に演習を終え、共通READMEの手順で削除と残存確認を行える。

Section 6では、既存の共通EKS環境を読み取り専用で観察します。ServiceAccount、RBAC、IAM policy、EKS access entry、Pod Identity associationを演習のために追加または変更しません。

## 公式資料

- [AWS CloudShellの環境とプリインストール済みソフトウェア](https://docs.aws.amazon.com/cloudshell/latest/userguide/vm-specs.html)
- [AWS CloudShellのRegionと保存領域](https://docs.aws.amazon.com/cloudshell/latest/userguide/working-with-aws-cloudshell.html)
- [AWS CloudShellの制限と永続領域](https://docs.aws.amazon.com/cloudshell/latest/userguide/limits.html)
